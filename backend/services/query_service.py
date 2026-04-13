import json
import os
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from services.chunk_serialization import serialize_chunk_reference
from services.llm_client import LLMError, OllamaClient
from services.planning_service import (
    build_deterministic_audit,
    build_planning_context,
    is_audit_question,
    render_deterministic_audit_answer,
)
from services.profile_service import get_student_payload
from services.retrieval_service import DEFAULT_QUERY_SOURCE_TYPES, get_retrieval_service
from services.verification import (
    PLANNING_CONTEXT_CITATION_ID,
    extract_citation_ids,
    planning_context_text,
    split_sentences,
    strip_citations,
    verify_answer,
)
from services.year_utils import expand_bulletin_year


DEFAULT_REFUSAL = (
    "I can only answer from the retrieved bulletin evidence, and the current "
    "evidence is not sufficient to answer this safely."
)
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
        citations.append(serialize_chunk_reference(row))
        seen.add(chunk_id)
    return citations


def serialize_retrieved_chunks(chunks: list[dict]) -> list[dict]:
    return [serialize_chunk_reference(chunk, include_score=True) for chunk in chunks]


class QueryService:
    def __init__(self) -> None:
        self.retrieval = get_retrieval_service()
        self.llm = OllamaClient()

    def answer_question(
        self,
        *,
        question: str,
        student_id: str | None = None,
        top_k: int = 1,
        include_prompt_debug: bool = False,
    ) -> dict:
        started_at = time.perf_counter()
        timings_ms: dict[str, int] = {}
        effective_top_k = 1
        prompt_debug_attempts: list[dict] = []

        student = get_student_payload(student_id) if student_id else None
        bulletin_year = student.get("bulletin_year") if student else None
        program = student.get("program") if student else None
        planning_context = build_planning_context(student) if student else None

        retrieval_started = time.perf_counter()
        retrieved_chunks = self.retrieval.hybrid_search(
            question,
            k=effective_top_k,
            bulletin_year=bulletin_year,
            program=program,
            source_types=DEFAULT_QUERY_SOURCE_TYPES,
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
                prompt_debug_attempts=prompt_debug_attempts if include_prompt_debug else None,
            )
            self._log_event(response, question=question, student=student)
            return response

        deterministic_audit = None
        if is_audit_question(question):
            deterministic_audit = build_deterministic_audit(
                planning_context=planning_context,
                retrieved_chunks=retrieved_chunks,
            )
        if deterministic_audit is not None:
            verification_started = time.perf_counter()
            deterministic_answer = render_deterministic_audit_answer(deterministic_audit).strip()
            verifier = verify_answer(
                deterministic_answer,
                retrieved_chunks,
                planning_context=planning_context,
            )
            timings_ms["generation"] = 0
            timings_ms["verification"] = round((time.perf_counter() - verification_started) * 1000)
            timings_ms["total"] = round((time.perf_counter() - started_at) * 1000)

            if verifier["passed"]:
                response = {
                    "status": "answered",
                    "answer": deterministic_answer,
                    "refusal_reason": None,
                    "citations": build_citation_payload(deterministic_answer, retrieved_chunks),
                    "retrieved_chunks": serialize_retrieved_chunks(retrieved_chunks),
                    "verifier": verifier,
                    "timings_ms": timings_ms,
                    "student_context": self._student_context(student),
                    "audit_summary": deterministic_audit,
                    "planning_context": self._serialize_planning_context(planning_context),
                }
                if include_prompt_debug:
                    response["prompt_debug"] = {"attempts": prompt_debug_attempts}
                self._log_event(response, question=question, student=student)
                return response

        generation_started = time.perf_counter()
        try:
            llm_result = self._generate_answer(
                question=question,
                retrieved_chunks=retrieved_chunks,
                student=student,
                planning_context=planning_context,
                prompt_debug_attempts=prompt_debug_attempts if include_prompt_debug else None,
                debug_stage="initial_answer",
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
                prompt_debug_attempts=prompt_debug_attempts if include_prompt_debug else None,
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
                planning_context=planning_context,
                prompt_debug_attempts=prompt_debug_attempts if include_prompt_debug else None,
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
                prompt_debug_attempts=prompt_debug_attempts if include_prompt_debug else None,
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
                prompt_debug_attempts=prompt_debug_attempts if include_prompt_debug else None,
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
            "audit_summary": deterministic_audit,
            "planning_context": self._serialize_planning_context(planning_context),
        }
        if include_prompt_debug:
            response["prompt_debug"] = {
                "attempts": prompt_debug_attempts,
            }
        self._log_event(response, question=question, student=student)
        return response

    def _generate_answer(
        self,
        *,
        question: str,
        retrieved_chunks: list[dict],
        student: dict | None,
        planning_context: dict | None,
        rewrite_feedback: list[str] | None = None,
        prior_answer: str | None = None,
        prompt_debug_attempts: list[dict] | None = None,
        debug_stage: str = "answer",
    ) -> dict:
        system_prompt = (
            "You are AdvisorAI. Use only the retrieved bulletin summary chunks and student information provided by the user. "
            "Do not use outside knowledge. If the evidence is insufficient, refuse. "
            "Return strict JSON with keys status, answer, refusal_reason. "
            "Explain why you think your answer is correct and explain how your answer fits into the context of the student's plan. "
            "When structured planning context is provided, treat it as the source of truth for the "
            "student's completed, in-progress, and planned courses. "
            "Never rely on unseen raw bulletin chunks; the summary chunks are the only bulletin evidence "
            "available to you in this prompt. "
            "The answer field must always be a plain JSON string, never an object or array. "
            "Valid status values are only answered or refused. "
            "If status is answered, every sentence in answer must end with one or more citations "
            "formatted like [23-24:007646], [23-24:007646, 23-24:007652], or [planning_context]. "
            "Use [planning_context] only for facts taken from the student's saved course history or "
            "planning data. Use bulletin chunk citations only for bulletin requirements or policy claims. "
            "Keep planning-context facts and bulletin-requirement facts in separate sentences whenever possible. "
            "Treat the 'Bulletin requirement evidence' section as catalog-derived requirements and rules, "
            "not as the student's personal course history or progress. "
            "If multiple bulletin years are cited, explicitly name the year in the answer text. "
            "Do not mention chunks that were not provided."
        )
        prompt = self._build_prompt(
            question=question,
            student=student,
            planning_context=planning_context,
            retrieved_chunks=retrieved_chunks,
            rewrite_feedback=rewrite_feedback,
            prior_answer=prior_answer,
        )
        retry_prompt = (
            prompt
            + "\nYour previous response was invalid. Return exactly one compact JSON object with "
              "keys status, answer, refusal_reason. Use only status=answered or status=refused. "
              "The answer value must be a plain JSON string."
        )
        last_error: LLMError | None = None

        for attempt, active_prompt in enumerate((prompt, retry_prompt), start=1):
            request_payload = self.llm.build_generate_payload(
                system_prompt=system_prompt,
                prompt=active_prompt,
            )
            if prompt_debug_attempts is not None:
                prompt_debug_attempts.append(
                    {
                        "stage": debug_stage,
                        "attempt": attempt,
                        "variant": "primary" if attempt == 1 else "json_retry",
                        "system_prompt": system_prompt,
                        "prompt": active_prompt,
                        "request_payload": deepcopy(request_payload),
                    }
                )
            try:
                result = self.llm.generate_json(
                    system_prompt=system_prompt,
                    prompt=active_prompt,
                    payload=request_payload,
                )
            except LLMError as exc:
                last_error = exc
                if attempt == 1 and "invalid JSON" in str(exc):
                    continue
                raise

            status_raw = result.get("status")
            answer_raw = result.get("answer")
            refusal_raw = result.get("refusal_reason")

            status = str(status_raw or "").strip().lower()
            answer = answer_raw.strip() if isinstance(answer_raw, str) else None
            refusal_reason = refusal_raw.strip() if isinstance(refusal_raw, str) else None

            schema_valid = (
                status in {"answered", "refused"}
                and (answer_raw is None or isinstance(answer_raw, str))
                and (refusal_raw is None or isinstance(refusal_raw, str))
            )
            if not schema_valid:
                last_error = LLMError(
                    "LLM returned invalid response schema: "
                    + json.dumps(result, ensure_ascii=True)[:1000]
                )
                if attempt == 1:
                    continue
                raise last_error

            if status == "refused":
                return {
                    "status": "refused",
                    "answer": "",
                    "refusal_reason": refusal_reason or DEFAULT_REFUSAL,
                }

            return {
                "status": "answered",
                "answer": answer or "",
                "refusal_reason": None,
            }

        raise last_error or LLMError("LLM generation failed.")

    def _verify_or_rewrite(
        self,
        *,
        question: str,
        initial_result: dict,
        retrieved_chunks: list[dict],
        student: dict | None,
        planning_context: dict | None,
        prompt_debug_attempts: list[dict] | None = None,
    ) -> dict:
        if initial_result["status"] != "answered":
            return {
                "status": "refused",
                "refusal_reason": initial_result.get("refusal_reason") or DEFAULT_REFUSAL,
                "verifier": {"passed": False, "issues": [initial_result.get("refusal_reason")]},
            }

        normalized_initial_answer = self._normalize_answer(initial_result["answer"])
        verifier = verify_answer(
            normalized_initial_answer,
            retrieved_chunks,
            planning_context=planning_context,
        )
        if verifier["passed"]:
            return {
                "status": "answered",
                "answer": normalized_initial_answer,
                "verifier": verifier,
            }

        repaired_answer = self._normalize_answer(
            self._repair_answer_citations(
                normalized_initial_answer,
                retrieved_chunks,
                planning_context,
            )
        )
        if repaired_answer != normalized_initial_answer:
            repaired_verifier = verify_answer(
                repaired_answer,
                retrieved_chunks,
                planning_context=planning_context,
            )
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
            planning_context=planning_context,
            rewrite_feedback=verifier["issues"],
            prior_answer=normalized_initial_answer,
            prompt_debug_attempts=prompt_debug_attempts,
            debug_stage="verification_rewrite",
        )
        if rewrite["status"] != "answered":
            return {
                "status": "refused",
                "refusal_reason": rewrite.get("refusal_reason") or DEFAULT_REFUSAL,
                "verifier": verifier,
            }

        rewritten_answer = self._normalize_answer(rewrite["answer"])
        rewritten_verifier = verify_answer(
            rewritten_answer,
            retrieved_chunks,
            planning_context=planning_context,
        )
        if rewritten_verifier["passed"]:
            return {
                "status": "answered",
                "answer": rewritten_answer,
                "verifier": rewritten_verifier,
            }

        return {
            "status": "refused",
            "refusal_reason": rewritten_verifier["issues"][0] if rewritten_verifier["issues"] else DEFAULT_REFUSAL,
            "verifier": rewritten_verifier,
        }

    def _normalize_answer(self, answer: str) -> str:
        sentences = split_sentences(answer)
        if not sentences:
            return ""

        cleaned_sentences: list[str] = []
        seen: set[str] = set()
        for sentence in sentences:
            normalized = re.sub(r"\s+", " ", sentence.strip())
            if not normalized or not strip_citations(normalized):
                continue
            if normalized in seen:
                continue
            cleaned_sentences.append(normalized)
            seen.add(normalized)

        return " ".join(cleaned_sentences)

    def _repair_answer_citations(
        self,
        answer: str,
        retrieved_chunks: list[dict],
        planning_context: dict | None,
    ) -> str:
        sentences = split_sentences(answer)
        if not sentences:
            return answer

        retrieved_ids = {chunk["chunkId"] for chunk in retrieved_chunks}
        repaired_sentences: list[str] = []
        changed = False
        for sentence in sentences:
            existing_ids = extract_citation_ids(sentence)
            invalid_existing_ids = [
                citation_id
                for citation_id in existing_ids
                if citation_id not in retrieved_ids and citation_id != PLANNING_CONTEXT_CITATION_ID
            ]
            citation_ids = self._find_supporting_citation_ids(
                sentence,
                retrieved_chunks,
                planning_context,
            )
            if not citation_ids:
                repaired_sentences.append(sentence)
                continue
            if existing_ids and not invalid_existing_ids:
                repaired_sentences.append(sentence)
                continue

            body = re.sub(r"\s+", " ", sentence.strip())
            body = re.sub(r"\[[^\]]+\]", "", body).strip()
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

    def _find_supporting_citation_ids(
        self,
        sentence: str,
        retrieved_chunks: list[dict],
        planning_context: dict | None,
    ) -> list[str]:
        body = re.sub(r"\[[^\]]+\]", "", sentence)
        body_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", body.lower())
            if len(token) > 2
        }
        if not body_tokens:
            return []

        scored: list[tuple[int, int, float, str]] = []
        planning_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", planning_context_text(planning_context).lower())
            if len(token) > 2
        }
        planning_overlap = sum(1 for token in body_tokens if token in planning_tokens)
        if planning_overlap > 0:
            scored.append((planning_overlap, 1, 0.0, PLANNING_CONTEXT_CITATION_ID))

        for chunk in retrieved_chunks:
            chunk_text = chunk.get("chunk", "").lower()
            overlap = sum(1 for token in body_tokens if token in chunk_text)
            if overlap <= 0:
                continue
            scored.append((overlap, 0, float(chunk.get("score") or 0.0), chunk["chunkId"]))

        scored.sort(reverse=True)
        if not scored:
            return []

        best_overlap = scored[0][0]
        best_priority = scored[0][1]
        return [
            chunk_id
            for overlap, priority, _, chunk_id in scored
            if overlap == best_overlap and priority == best_priority
        ][:1]

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
            "completed_courses": compact_courses(
                planning_context.get("completed_courses", []),
                6,
            ),
            "in_progress_course_codes": planning_context.get("in_progress_course_codes", [])[:8],
            "planned_course_codes": planning_context.get("planned_course_codes", [])[:8],
            "in_progress_courses": compact_courses(
                planning_context.get("in_progress_courses", []),
                4,
            ),
            "planned_courses": compact_courses(
                planning_context.get("planned_courses", []),
                4,
            ),
        }

    def _prompt_ready_chunks(self, retrieved_chunks: list[dict]) -> list[dict]:
        prompt_chunks: list[dict] = []
        for chunk in retrieved_chunks:
            structured = chunk.get("structuredData")
            structured_kind = structured.get("kind") if isinstance(structured, dict) else None
            chunk_text = chunk.get("chunk", "").strip()

            if not chunk_text:
                continue

            prompt_chunks.append(
                {
                    "recordType": "bulletin_requirement_evidence",
                    "evidenceLabel": "course_requirements_and_bulletin_rules",
                    "chunkId": chunk["chunkId"],
                    "bulletin": expand_bulletin_year(chunk["bulletin"]) or chunk["bulletin"],
                    "pageOccurrence": chunk.get("pageOccurrence") or [],
                    "programPageOccurrence": chunk.get("programPageOccurrence") or [],
                    "sourceType": chunk.get("sourceType"),
                    "program": chunk.get("program"),
                    "sectionTitle": chunk.get("sectionTitle"),
                    "sectionType": chunk.get("sectionType"),
                    "sourceChunkIds": (chunk.get("sourceChunkIds") or [])[:8],
                    "structuredDataKind": structured_kind,
                    "text": chunk_text,
                }
            )

        return prompt_chunks

    def _build_prompt(
        self,
        *,
        question: str,
        student: dict | None,
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

        if planning_context:
            lines.append("Structured planning context:")
            lines.append(
                json.dumps(self._compact_planning_context(planning_context), indent=2)
            )
            lines.append(
                "For planning questions, use the structured planning context for the student's saved "
                "course history and current registrations. Use bulletin chunks to infer what matters "
                "for the plan."
            )

        if prior_answer and rewrite_feedback:
            lines.append("Your previous draft failed verification.")
            lines.append(f"Previous draft: {prior_answer}")
            lines.append("Fix these issues exactly:")
            for issue in rewrite_feedback:
                lines.append(f"- {issue}")

        lines.append("Bulletin requirement evidence:")
        lines.append(
            "Everything in this section is bulletin-derived requirement evidence, not student-specific "
            "course history, enrollment, or progress data."
        )
        for chunk in self._prompt_ready_chunks(retrieved_chunks):
            lines.append(json.dumps(chunk, ensure_ascii=True))

        lines.append(
            "These retrieved chunks are structured bulletin summaries. "
            "A chunk may represent a full program profile with all requirements or a legacy section-level summary. "
            "Treat sourceChunkIds as provenance only, not as additional text you can read."
        )

        lines.append(
            "If the chunks are insufficient, return "
            '{"status":"refused","answer":"","refusal_reason":"..."}'
        )
        return "\n".join(lines)

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
        prompt_debug_attempts: list[dict] | None = None,
    ) -> dict:
        timings_ms.setdefault("total", timings_ms.get("retrieval", 0) + timings_ms.get("generation", 0) + timings_ms.get("verification", 0))
        response = {
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
        if prompt_debug_attempts is not None:
            response["prompt_debug"] = {
                "attempts": prompt_debug_attempts,
            }
        return response

    def _student_context(self, student: dict | None) -> dict | None:
        if not student:
            return None
        return {
            "student_id": student["student_id"],
            "name": student["name"],
            "program": student["program"],
            "bulletin_year": student["bulletin_year"],
        }

    def _serialize_planning_context(self, planning_context: dict | None) -> dict | None:
        if not planning_context:
            return None
        return {
            "program": planning_context["program"],
            "bulletin_year": planning_context["bulletin_year"],
            "completed_course_codes": planning_context.get("completed_course_codes", []),
            "completed_courses": planning_context.get("completed_courses", []),
            "in_progress_course_codes": planning_context.get("in_progress_course_codes", []),
            "planned_course_codes": planning_context.get("planned_course_codes", []),
            "completed_credits": planning_context.get("completed_credits"),
            "in_progress_credits": planning_context.get("in_progress_credits"),
            "planned_credits": planning_context.get("planned_credits"),
            "in_progress_courses": planning_context.get("in_progress_courses", []),
            "planned_courses": planning_context.get("planned_courses", []),
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
        if response.get("prompt_debug") is not None:
            event["prompt_debug"] = response["prompt_debug"]
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
