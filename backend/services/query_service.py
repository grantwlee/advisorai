import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from services.degree_audit import is_degree_audit_question, summarize_degree_audit
from services.llm_client import LLMError, OllamaClient
from services.planning_service import build_planning_context, is_planning_question
from services.profile_service import get_student_payload
from services.retrieval_service import get_retrieval_service
from services.verification import extract_citation_ids, split_sentences, verify_answer
from services.year_utils import expand_bulletin_year


DEFAULT_REFUSAL = (
    "I can only answer from the retrieved bulletin evidence, and the current "
    "evidence is not sufficient to answer this safely."
)
PROMPT_CHUNK_CHAR_LIMIT = int(os.getenv("LLM_PROMPT_CHUNK_CHAR_LIMIT", "600"))
PROMPT_TOTAL_CHARS = int(os.getenv("LLM_PROMPT_TOTAL_CHARS", "2400"))
LOG_PATH = Path(
    os.getenv(
        "QUERY_LOG_PATH",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "query_logs.jsonl"),
    )
)


def build_citation_payload(answer: str, retrieved_chunks: list[dict]) -> list[dict]:
    by_id = {chunk["chunkId"]: chunk for chunk in retrieved_chunks}
    citations = []
    seen = set()
    for chunk_id in extract_citation_ids(answer):
        if chunk_id in seen or chunk_id not in by_id:
            continue
        row = by_id[chunk_id]
        citations.append(
            {
                "chunkId": row["chunkId"],
                "bulletin": row["bulletin"],
                "pageOccurrence": row.get("pageOccurrence") or [],
                "preview": row["preview"],
                "sourcePdf": row.get("sourcePdf"),
            }
        )
        seen.add(chunk_id)
    return citations


def serialize_retrieved_chunks(chunks: list[dict]) -> list[dict]:
    return [
        {
            "chunkId": chunk["chunkId"],
            "bulletin": chunk["bulletin"],
            "pageOccurrence": chunk.get("pageOccurrence") or [],
            "preview": chunk["preview"],
            "sourcePdf": chunk.get("sourcePdf"),
            "score": chunk.get("score"),
        }
        for chunk in chunks
    ]
class QueryService:
    def __init__(self) -> None:
        self.retrieval = get_retrieval_service()
        self.llm = OllamaClient()

    def answer_question(
        self,
        *,
        question: str,
        student_id: str | None = None,
        top_k: int = 5,
    ) -> dict:
        started_at = time.perf_counter()
        timings_ms: dict[str, int] = {}

        student = get_student_payload(student_id) if student_id else None
        bulletin_year = student.get("bulletin_year") if student else None
        program = student.get("program") if student else None
        audit_summary = summarize_degree_audit(student) if student else None
        planning_context = build_planning_context(student, audit_summary=audit_summary)
        planning_question = is_planning_question(question)

        retrieval_started = time.perf_counter()
        if audit_summary:
            if planning_question and planning_context:
                retrieved_chunks = self._retrieve_planning_chunks(
                    question,
                    planning_context,
                    top_k=max(top_k, 6),
                )
            elif is_degree_audit_question(question):
                retrieved_chunks = self._retrieve_degree_audit_chunks(
                    audit_summary,
                    top_k=max(top_k, 6),
                )
            else:
                retrieved_chunks = self.retrieval.hybrid_search(
                    question,
                    k=top_k,
                    bulletin_year=bulletin_year,
                    program=program,
                )
        else:
            retrieved_chunks = self.retrieval.hybrid_search(
                question,
                k=top_k,
                bulletin_year=bulletin_year,
                program=program,
            )
        timings_ms["retrieval"] = round((time.perf_counter() - retrieval_started) * 1000)

        if not retrieved_chunks:
            response = self._refusal_response(
                question=question,
                student=student,
                retrieved_chunks=[],
                refusal_reason=DEFAULT_REFUSAL,
                verifier={"passed": True, "issues": []},
                timings_ms=timings_ms,
                planning_context=planning_context,
            )
            self._log_event(response, question=question, student=student)
            return response

        generation_started = time.perf_counter()
        try:
            llm_result = self._generate_answer(
                question=question,
                retrieved_chunks=retrieved_chunks,
                student=student,
                audit_summary=audit_summary,
                planning_context=planning_context,
            )
        except LLMError as exc:
            timings_ms["generation"] = round((time.perf_counter() - generation_started) * 1000)
            response = self._refusal_response(
                question=question,
                student=student,
                retrieved_chunks=retrieved_chunks,
                refusal_reason=str(exc),
                verifier={"passed": False, "issues": [str(exc)]},
                timings_ms=timings_ms,
                planning_context=planning_context,
            )
            self._log_event(response, question=question, student=student)
            return response

        timings_ms["generation"] = round((time.perf_counter() - generation_started) * 1000)

        verification_started = time.perf_counter()
        try:
            verified = self._verify_or_rewrite(
                question=question,
                initial_result=llm_result,
                retrieved_chunks=retrieved_chunks,
                student=student,
                audit_summary=audit_summary,
                planning_context=planning_context,
            )
        except LLMError as exc:
            timings_ms["verification"] = round((time.perf_counter() - verification_started) * 1000)
            timings_ms["total"] = round((time.perf_counter() - started_at) * 1000)
            response = self._refusal_response(
                question=question,
                student=student,
                retrieved_chunks=retrieved_chunks,
                refusal_reason=str(exc),
                verifier={"passed": False, "issues": [str(exc)]},
                timings_ms=timings_ms,
                planning_context=planning_context,
            )
            self._log_event(response, question=question, student=student)
            return response

        timings_ms["verification"] = round((time.perf_counter() - verification_started) * 1000)
        timings_ms["total"] = round((time.perf_counter() - started_at) * 1000)

        if verified["status"] != "answered":
            response = self._refusal_response(
                question=question,
                student=student,
                retrieved_chunks=retrieved_chunks,
                refusal_reason=verified.get("refusal_reason") or DEFAULT_REFUSAL,
                verifier=verified.get("verifier") or {"passed": False, "issues": []},
                timings_ms=timings_ms,
                planning_context=planning_context,
            )
            self._log_event(response, question=question, student=student)
            return response

        answer = verified["answer"].strip()
        citations = build_citation_payload(answer, retrieved_chunks)
        response = {
            "status": "answered",
            "answer": answer,
            "refusal_reason": None,
            "citations": citations,
            "retrieved_chunks": serialize_retrieved_chunks(retrieved_chunks),
            "verifier": verified["verifier"],
            "timings_ms": timings_ms,
            "student_context": self._student_context(student),
            "audit_summary": self._serialize_audit_summary(audit_summary),
            "planning_context": self._serialize_planning_context(planning_context),
        }
        self._log_event(response, question=question, student=student)
        return response

    def _generate_answer(
        self,
        *,
        question: str,
        retrieved_chunks: list[dict],
        student: dict | None,
        audit_summary: dict | None,
        planning_context: dict | None,
        rewrite_feedback: list[str] | None = None,
        prior_answer: str | None = None,
    ) -> dict:
        system_prompt = (
            "You are AdvisorAI. Use only the retrieved bulletin chunks provided by the user. "
            "Do not use outside knowledge. If the evidence is insufficient, refuse. "
            "Return strict JSON with keys status, answer, refusal_reason. "
            "Keep answers brief: at most 2 sentences unless the question is a degree-audit question. "
            "When structured planning context is provided, treat it as the source of truth for the "
            "student's completed, in-progress, and recommended courses. "
            "If status is answered, every sentence in answer must end with one or more chunk citations "
            "formatted like [23-24:007646] or [23-24:007646, 23-24:007652]. "
            "If multiple bulletin years are cited, explicitly name the year in the answer text. "
            "Do not mention chunks that were not provided."
        )
        prompt = self._build_prompt(
            question=question,
            student=student,
            audit_summary=audit_summary,
            planning_context=planning_context,
            retrieved_chunks=retrieved_chunks,
            rewrite_feedback=rewrite_feedback,
            prior_answer=prior_answer,
        )
        result = self.llm.generate_json(system_prompt=system_prompt, prompt=prompt)
        status = str(result.get("status") or "").strip().lower()
        answer = str(result.get("answer") or "").strip()
        refusal_reason = str(result.get("refusal_reason") or "").strip() or None

        if status not in {"answered", "refused"}:
            if answer:
                status = "answered"
            else:
                status = "refused"

        if status == "refused":
            return {
                "status": "refused",
                "answer": "",
                "refusal_reason": refusal_reason or DEFAULT_REFUSAL,
            }

        return {
            "status": "answered",
            "answer": answer,
            "refusal_reason": None,
        }

    def _verify_or_rewrite(
        self,
        *,
        question: str,
        initial_result: dict,
        retrieved_chunks: list[dict],
        student: dict | None,
        audit_summary: dict | None,
        planning_context: dict | None,
    ) -> dict:
        if initial_result["status"] != "answered":
            return {
                "status": "refused",
                "refusal_reason": initial_result.get("refusal_reason") or DEFAULT_REFUSAL,
                "verifier": {"passed": False, "issues": [initial_result.get("refusal_reason")]},
            }

        verifier = verify_answer(initial_result["answer"], retrieved_chunks)
        if verifier["passed"]:
            return {
                "status": "answered",
                "answer": initial_result["answer"],
                "verifier": verifier,
            }

        repaired_answer = self._repair_answer_citations(
            initial_result["answer"],
            retrieved_chunks,
        )
        if repaired_answer != initial_result["answer"]:
            repaired_verifier = verify_answer(repaired_answer, retrieved_chunks)
            if repaired_verifier["passed"]:
                return {
                    "status": "answered",
                    "answer": repaired_answer,
                    "verifier": repaired_verifier,
                }

        rewrite = self._generate_answer(
            question=question,
            retrieved_chunks=retrieved_chunks,
            student=student,
            audit_summary=audit_summary,
            planning_context=planning_context,
            rewrite_feedback=verifier["issues"],
            prior_answer=initial_result["answer"],
        )
        if rewrite["status"] != "answered":
            return {
                "status": "refused",
                "refusal_reason": rewrite.get("refusal_reason") or DEFAULT_REFUSAL,
                "verifier": verifier,
            }

        rewritten_verifier = verify_answer(rewrite["answer"], retrieved_chunks)
        if rewritten_verifier["passed"]:
            return {
                "status": "answered",
                "answer": rewrite["answer"],
                "verifier": rewritten_verifier,
            }

        return {
            "status": "refused",
            "refusal_reason": DEFAULT_REFUSAL,
            "verifier": rewritten_verifier,
        }

    def _repair_answer_citations(self, answer: str, retrieved_chunks: list[dict]) -> str:
        sentences = split_sentences(answer)
        if not sentences:
            return answer

        repaired_sentences: list[str] = []
        changed = False
        for sentence in sentences:
            if extract_citation_ids(sentence):
                repaired_sentences.append(sentence)
                continue

            citation_ids = self._find_supporting_chunk_ids(sentence, retrieved_chunks)
            if not citation_ids:
                repaired_sentences.append(sentence)
                continue

            body = re.sub(r"\s+", " ", sentence.strip())
            match = re.match(r"^(.*?)([.!?]+)?$", body)
            sentence_body = (match.group(1) or "").strip() if match else body
            punctuation = match.group(2) or ""
            repaired_sentences.append(
                f"{sentence_body} [{', '.join(citation_ids)}]{punctuation}"
            )
            changed = True

        if not changed:
            return answer

        return " ".join(repaired_sentences)

    def _find_supporting_chunk_ids(self, sentence: str, retrieved_chunks: list[dict]) -> list[str]:
        body = re.sub(r"\[[^\]]+\]", "", sentence)
        body_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", body.lower())
            if len(token) > 2
        }
        if not body_tokens:
            return []

        scored: list[tuple[int, float, str]] = []
        for chunk in retrieved_chunks:
            chunk_text = chunk.get("chunk", "").lower()
            overlap = sum(1 for token in body_tokens if token in chunk_text)
            if overlap <= 0:
                continue
            scored.append((overlap, float(chunk.get("score") or 0.0), chunk["chunkId"]))

        scored.sort(reverse=True)
        if not scored:
            return []

        best_overlap = scored[0][0]
        return [chunk_id for overlap, _, chunk_id in scored if overlap == best_overlap][:2]

    def _compact_planning_context(self, planning_context: dict | None) -> dict | None:
        if not planning_context:
            return None

        def compact_courses(rows: list[dict], limit: int) -> list[dict]:
            return [
                {
                    "code": row.get("code"),
                    "title": row.get("title"),
                    "credits": row.get("credits"),
                }
                for row in rows[:limit]
            ]

        return {
            "program": planning_context["program"],
            "bulletin_year": planning_context["bulletin_year"],
            "completed_course_codes": planning_context.get("completed_course_codes", [])[:12],
            "in_progress_course_codes": planning_context.get("in_progress_course_codes", [])[:8],
            "planned_course_codes": planning_context.get("planned_course_codes", [])[:8],
            "remaining_requirement_count": planning_context.get("remaining_requirement_count"),
            "remaining_credits": planning_context.get("remaining_credits"),
            "recommended_next_courses": compact_courses(
                planning_context.get("recommended_next_courses", []),
                4,
            ),
            "blocked_courses": compact_courses(
                planning_context.get("blocked_courses", []),
                3,
            ),
        }

    def _prompt_ready_chunks(self, retrieved_chunks: list[dict]) -> list[dict]:
        budget_remaining = PROMPT_TOTAL_CHARS
        prompt_chunks: list[dict] = []
        for chunk in retrieved_chunks:
            if budget_remaining <= 0:
                break

            chunk_text = re.sub(r"\s+", " ", chunk.get("chunk", "")).strip()
            truncated = chunk_text[: min(PROMPT_CHUNK_CHAR_LIMIT, budget_remaining)].strip()
            if not truncated:
                continue

            if len(chunk_text) > len(truncated):
                truncated = truncated.rstrip() + " ..."

            prompt_chunks.append(
                {
                    "chunkId": chunk["chunkId"],
                    "bulletin": expand_bulletin_year(chunk["bulletin"]) or chunk["bulletin"],
                    "pageOccurrence": chunk.get("pageOccurrence") or [],
                    "text": truncated,
                }
            )
            budget_remaining -= len(truncated)

        return prompt_chunks

    def _build_prompt(
        self,
        *,
        question: str,
        student: dict | None,
        audit_summary: dict | None,
        planning_context: dict | None,
        retrieved_chunks: list[dict],
        rewrite_feedback: list[str] | None,
        prior_answer: str | None,
    ) -> str:
        lines = [f"User question: {question.strip()}"]
        if student:
            lines.append(
                "Student context: "
                f"{student['name']} ({student['student_id']}), "
                f"program={student['program']}, bulletin_year={student['bulletin_year']}."
            )

        if audit_summary:
            lines.append("Deterministic degree-audit summary:")
            lines.append(
                json.dumps(self._serialize_audit_summary(audit_summary), indent=2)
            )
            lines.append(
                "For audit questions, only describe the deterministic result above. "
                "Do not invent requirements outside that summary."
            )

        if planning_context:
            lines.append("Structured planning context:")
            lines.append(
                json.dumps(self._compact_planning_context(planning_context), indent=2)
            )
            lines.append(
                "For planning questions, use the structured planning context as the source of truth "
                "for the student's progress and recommended next courses. Use bulletin chunks only "
                "to support or qualify that plan."
            )

        if prior_answer and rewrite_feedback:
            lines.append("Your previous draft failed verification.")
            lines.append(f"Previous draft: {prior_answer}")
            lines.append("Fix these issues exactly:")
            for issue in rewrite_feedback:
                lines.append(f"- {issue}")

        lines.append("Retrieved chunks:")
        for chunk in self._prompt_ready_chunks(retrieved_chunks):
            lines.append(json.dumps(chunk, ensure_ascii=True))

        lines.append(
            "If the chunks are insufficient, return "
            '{"status":"refused","answer":"","refusal_reason":"..."}'
        )
        return "\n".join(lines)

    def _retrieve_degree_audit_chunks(self, audit_summary: dict, top_k: int) -> list[dict]:
        chunk_by_id: dict[str, dict] = {}
        bulletin_year = audit_summary.get("bulletin_year")
        program = audit_summary.get("program")
        queries = []
        if audit_summary.get("summary_query"):
            queries.append(audit_summary["summary_query"])

        prioritized = audit_summary.get("remaining") or audit_summary.get("in_progress") or []
        for requirement in prioritized[:4]:
            queries.append(requirement.get("citation_query") or f"{program} {requirement['code']}")

        for query in queries:
            for chunk in self.retrieval.hybrid_search(
                query,
                k=2,
                bulletin_year=bulletin_year,
                program=program,
            ):
                chunk_by_id.setdefault(chunk["chunkId"], chunk)
                if len(chunk_by_id) >= top_k:
                    break
            if len(chunk_by_id) >= top_k:
                break

        return list(chunk_by_id.values())[:top_k]

    def _retrieve_planning_chunks(
        self,
        question: str,
        planning_context: dict,
        top_k: int,
    ) -> list[dict]:
        chunk_by_id: dict[str, dict] = {}
        queries = [question]
        if planning_context.get("summary_query"):
            queries.insert(0, planning_context["summary_query"])

        for requirement in planning_context.get("recommended_next_courses", [])[:3]:
            queries.append(requirement.get("citation_query") or requirement["code"])
        for requirement in planning_context.get("blocked_courses", [])[:2]:
            queries.append(requirement.get("citation_query") or requirement["code"])
        for requirement in planning_context.get("planned_courses", [])[:1]:
            queries.append(requirement.get("citation_query") or requirement["code"])

        for query in queries:
            for chunk in self.retrieval.hybrid_search(
                query,
                k=2,
                bulletin_year=planning_context.get("bulletin_year"),
                program=planning_context.get("program"),
            ):
                chunk_by_id.setdefault(chunk["chunkId"], chunk)
                if len(chunk_by_id) >= top_k:
                    break
            if len(chunk_by_id) >= top_k:
                break

        return list(chunk_by_id.values())[:top_k]

    def _refusal_response(
        self,
        *,
        question: str,
        student: dict | None,
        retrieved_chunks: list[dict],
        refusal_reason: str,
        verifier: dict,
        timings_ms: dict,
        planning_context: dict | None,
    ) -> dict:
        timings_ms.setdefault("total", timings_ms.get("retrieval", 0) + timings_ms.get("generation", 0) + timings_ms.get("verification", 0))
        return {
            "status": "refused",
            "answer": "",
            "refusal_reason": refusal_reason,
            "citations": [],
            "retrieved_chunks": serialize_retrieved_chunks(retrieved_chunks),
            "verifier": verifier,
            "timings_ms": timings_ms,
            "student_context": self._student_context(student),
            "audit_summary": None,
            "planning_context": self._serialize_planning_context(planning_context),
        }

    def _student_context(self, student: dict | None) -> dict | None:
        if not student:
            return None
        return {
            "student_id": student["student_id"],
            "name": student["name"],
            "program": student["program"],
            "bulletin_year": student["bulletin_year"],
        }

    def _serialize_audit_summary(self, audit_summary: dict | None) -> dict | None:
        if not audit_summary:
            return None
        return {
            "program": audit_summary["program"],
            "bulletin_year": audit_summary["bulletin_year"],
            "scope_note": audit_summary.get("scope_note"),
            "total_required": audit_summary["total_required"],
            "completed": audit_summary["completed"],
            "in_progress": audit_summary["in_progress"],
            "remaining": audit_summary["remaining"],
        }

    def _serialize_planning_context(self, planning_context: dict | None) -> dict | None:
        if not planning_context:
            return None
        return {
            "program": planning_context["program"],
            "bulletin_year": planning_context["bulletin_year"],
            "scope_note": planning_context.get("scope_note"),
            "completed_course_codes": planning_context.get("completed_course_codes", []),
            "in_progress_course_codes": planning_context.get("in_progress_course_codes", []),
            "planned_course_codes": planning_context.get("planned_course_codes", []),
            "completed_credits": planning_context.get("completed_credits"),
            "in_progress_credits": planning_context.get("in_progress_credits"),
            "planned_credits": planning_context.get("planned_credits"),
            "remaining_requirement_count": planning_context.get("remaining_requirement_count"),
            "remaining_credits": planning_context.get("remaining_credits"),
            "recommended_next_courses": planning_context.get("recommended_next_courses", []),
            "planned_courses": planning_context.get("planned_courses", []),
            "blocked_courses": planning_context.get("blocked_courses", []),
            "context_gaps": planning_context.get("context_gaps", []),
        }

    def _log_event(self, response: dict, *, question: str, student: dict | None) -> None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "student_context": self._student_context(student),
            "status": response["status"],
            "refusal_reason": response.get("refusal_reason"),
            "retrieved_chunk_ids": [
                row["chunkId"] for row in response.get("retrieved_chunks", [])
            ],
            "cited_chunk_ids": [
                row["chunkId"] for row in response.get("citations", [])
            ],
            "verifier": response.get("verifier"),
            "timings_ms": response.get("timings_ms"),
            "planning_context": response.get("planning_context"),
        }
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
