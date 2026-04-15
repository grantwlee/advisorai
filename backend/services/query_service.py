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
    build_planning_context,
    enrich_planning_context,
    is_planning_question,
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
AUDIT_KEYWORDS = (
    "what do i have left",
    "what do i still need",
    "what courses do i have left",
    "what courses are left",
    "remaining courses",
    "remaining requirements",
    "degree audit",
    "audit my degree",
    "not taken yet",
    "not in progress",
    "left in my program",
    "left in my major",
)
PROGRAM_EXPLORATION_KEYWORDS = (
    "switch major",
    "switch majors",
    "change major",
    "change majors",
    "switch program",
    "switch programs",
    "change program",
    "change programs",
    "different major",
    "another major",
    "other major",
    "other majors",
    "different program",
    "another program",
    "other program",
    "other programs",
    "switch from",
    "change from",
    "transfer to",
    "move to",
    "instead of",
)


def _planning_context_citation_payload(planning_context: dict | None) -> dict | None:
    if not planning_context:
        return None

    summary = planning_context_text(planning_context).strip()
    if not summary:
        return None

    bulletin = planning_context.get("bulletin_year") or "student profile"
    return {
        "chunkId": PLANNING_CONTEXT_CITATION_ID,
        "bulletin": bulletin,
        "pageOccurrence": [],
        "programPageOccurrence": [],
        "sourcePageOccurrence": [],
        "sourceChunkIds": planning_context.get("derived_from_chunk_ids") or [],
        "preview": summary[:300],
        "chunk": summary,
        "sourcePdf": None,
        "sourceType": "planning_context",
        "program": planning_context.get("program"),
        "sectionTitle": "Student planning context",
        "sectionType": "planning_context",
        "structuredData": None,
    }


def build_citation_payload(
    answer: str,
    retrieved_chunks: list[dict],
    planning_context: dict | None = None,
) -> list[dict]:
    by_id = {chunk["chunkId"]: chunk for chunk in retrieved_chunks}
    citations = []
    seen = set()
    for chunk_id in extract_citation_ids(answer):
        if chunk_id in seen:
            continue
        if chunk_id == PLANNING_CONTEXT_CITATION_ID:
            row = _planning_context_citation_payload(planning_context)
            if row is None:
                continue
        elif chunk_id in by_id:
            row = by_id[chunk_id]
        else:
            continue
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
        effective_top_k = max(2, top_k)
        prompt_debug_attempts: list[dict] = []

        student = get_student_payload(student_id) if student_id else None
        normalized_question = question.lower().strip()
        bulletin_year = student.get("bulletin_year") if student else None
        program = (
            student.get("program")
            if student and self._should_scope_retrieval_to_student_program(normalized_question)
            else None
        )
        planning_context = build_planning_context(student) if student else None

        retrieval_started = time.perf_counter()
        retrieved_chunks = self.retrieval.hybrid_search(
            question,
            k=effective_top_k,
            bulletin_year=bulletin_year,
            program=program,
            source_types=DEFAULT_QUERY_SOURCE_TYPES,
        )
        planning_context = enrich_planning_context(planning_context, retrieved_chunks)
        timings_ms["retrieval"] = round((time.perf_counter() - retrieval_started) * 1000)
        planning_grounding_summary = self._build_deterministic_planning_answer(
            question=question,
            planning_context=planning_context,
            retrieved_chunks=retrieved_chunks,
        )

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

        generation_started = time.perf_counter()
        try:
            llm_result = self._generate_answer(
                question=question,
                retrieved_chunks=retrieved_chunks,
                student=student,
                planning_context=planning_context,
                planning_grounding_summary=planning_grounding_summary,
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
                planning_grounding_summary=planning_grounding_summary,
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
        citations = build_citation_payload(
            answer,
            retrieved_chunks,
            planning_context=planning_context,
        )
        response = {
            "status": "answered",
            "answer": answer,
            "refusal_reason": None,
            "citations": citations,
            "retrieved_chunks": serialize_retrieved_chunks(retrieved_chunks),
            "verifier": verified["verifier"],
            "timings_ms": timings_ms,
            "student_context": self._student_context(student),
            "audit_summary": None,
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
        planning_grounding_summary: str | None = None,
        rewrite_feedback: list[str] | None = None,
        prior_answer: str | None = None,
        prompt_debug_attempts: list[dict] | None = None,
        debug_stage: str = "answer",
    ) -> dict:
        normalized_question = question.lower().strip()
        grounded_planning_question = bool(planning_grounding_summary) and (
            self._is_audit_question(normalized_question) or is_planning_question(question)
        )
        selected_model = self._select_model_for_question(
            normalized_question=normalized_question,
            grounded_planning_question=grounded_planning_question,
        )
        system_prompt = (
            "You are AdvisorAI. Use only the retrieved bulletin summary chunks and student information provided by the user. "
            "Do not use outside knowledge. If the evidence is insufficient, refuse. "
            "Return strict JSON with keys status, answer, refusal_reason. "
            "Explain why you think your answer is correct and explain how your answer fits into the context of the student's plan. "
            "When structured planning context is provided, treat it as the source of truth for the "
            "student's completed, in-progress, and planned courses. "
            "When a derived planning grounding summary is provided, treat it as grounded computation "
            "over the retrieved structured profile and do not contradict it unless the retrieved "
            "bulletin evidence explicitly requires a narrower answer. "
            "If the question is about remaining requirements or next courses and a derived planning "
            "grounding summary is provided, that summary is sufficient for a scoped planning answer, "
            "so do not refuse merely because a full university audit or prerequisite graph is unavailable. "
            "Never rely on unseen raw bulletin chunks; the summary chunks are the only bulletin evidence "
            "available to you in this prompt. "
            "The answer field must always be a plain JSON string, never an object or array. "
            "Valid status values are only answered or refused. "
            "If status is answered, the full answer must have at least one citation "
            "formatted like [23-24:007646], [23-24:007646, 23-24:007652], or [planning_context]. "
            "Use [planning_context] only for facts taken from the student's saved course history or "
            "planning data. Use bulletin chunk citations only for bulletin requirements or policy claims. "
            "If the question involves switching, comparing, or choosing between majors or programs, "
            "cite the relevant bulletin chunk for each program-specific requirement claim when that "
            "chunk is available in the prompt. Prefer bulletin chunk citations over [planning_context] "
            "for degree requirement comparisons across programs. "
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
            planning_grounding_summary=planning_grounding_summary,
            retrieved_chunks=retrieved_chunks,
            rewrite_feedback=rewrite_feedback,
            prior_answer=prior_answer,
        )
        retry_prompt = (
            prompt
            + "\nYour previous response was invalid. Return exactly one compact JSON object with "
              "keys status, answer, refusal_reason. Use only status=answered or status=refused. "
              "The answer value must be a plain JSON string. "
              "If status=answered, answer must contain at least one substantive sentence with "
              "words outside citations; do not return an empty string, [], or citation-only text. "
              "If you cannot produce a supported non-empty answer, use status=refused."
        )
        if grounded_planning_question:
            retry_prompt += (
                "\nFor this planning/audit question, the structured planning context and derived "
                "planning grounding summary already contain enough information for a scoped answer. "
                "Do not refuse for insufficient information. Answer from the provided remaining-course "
                "lists, counts, recommendations, and scope notes, and cite planning-derived facts as "
                "[planning_context]."
            )
        last_error: LLMError | None = None

        for attempt, active_prompt in enumerate((prompt, retry_prompt), start=1):
            request_payload = self.llm.build_generate_payload(
                system_prompt=system_prompt,
                prompt=active_prompt,
            )
            request_payload["model"] = selected_model
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

            if status == "answered" and not self._has_substantive_answer_text(answer or ""):
                last_error = LLMError(
                    "LLM returned answered status without substantive answer text."
                )
                if attempt == 1:
                    continue
                return {
                    "status": "refused",
                    "answer": "",
                    "refusal_reason": DEFAULT_REFUSAL,
                }

            if status == "refused":
                if grounded_planning_question and attempt == 1:
                    last_error = LLMError(
                        refusal_reason
                        or "LLM refused despite grounded planning context."
                    )
                    continue
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

    def _build_deterministic_planning_answer(
        self,
        *,
        question: str,
        planning_context: dict | None,
        retrieved_chunks: list[dict],
    ) -> str | None:
        if not planning_context:
            return None

        normalized_question = question.lower().strip()
        is_audit = self._is_audit_question(normalized_question)
        is_plan = is_planning_question(question)
        if not is_audit and not is_plan:
            return None

        if not planning_context.get("derived_from_chunk_ids"):
            return None

        sentences: list[str] = []
        policy_citation = self._policy_citation_id(planning_context, retrieved_chunks)
        scope_note = planning_context.get("scope_note")
        if scope_note:
            sentences.append(
                "This summary is based on your saved course history and the retrieved structured "
                "program profile, so it covers structured program requirements rather than a full "
                f"university audit [planning_context]."
            )

        completed_codes = planning_context.get("completed_course_codes", [])
        if completed_codes:
            sentences.append(
                "You have completed "
                + self._join_items(completed_codes)
                + " [planning_context]."
            )

        in_progress_codes = planning_context.get("in_progress_course_codes", [])
        if in_progress_codes:
            sentences.append(
                "You are currently taking "
                + self._join_items(in_progress_codes)
                + " [planning_context]."
            )

        remaining_core_codes = planning_context.get("remaining_core_course_codes", [])
        choose_three_remaining_count = planning_context.get("choose_three_remaining_count")
        choose_three_options = [
            row.get("code")
            for row in planning_context.get("choose_three_remaining_options", [])
            if row.get("code")
        ]

        if is_plan:
            recommended = [row.get("code") for row in planning_context.get("recommended_next_courses", []) if row.get("code")]
            if recommended:
                sentences.append(
                    "Based on the remaining core requirements in the retrieved profile, the next "
                    "courses to prioritize are "
                    + self._join_items(recommended)
                    + " [planning_context]."
                )
            remaining_after_recommended = [
                code for code in remaining_core_codes if code not in set(recommended)
            ]
            if remaining_after_recommended:
                sentences.append(
                    "Other unmet core courses in the retrieved profile are "
                    + self._join_items(remaining_after_recommended)
                    + " [planning_context]."
                )
            if choose_three_remaining_count and choose_three_options:
                sentences.append(
                    f"You also still need {choose_three_remaining_count} course"
                    + ("s" if choose_three_remaining_count != 1 else "")
                    + " from the Choose Three pool, with current options including "
                    + self._join_items(choose_three_options)
                    + " [planning_context]."
                )
            sentences.append(
                "This recommendation does not validate prerequisite sequencing, term availability, "
                "or schedule conflicts [planning_context]."
            )
            if policy_citation:
                if self._chunk_mentions_andrews_core(retrieved_chunks, policy_citation):
                    sentences.append(
                        f"You still need to satisfy the Andrews Core Experience requirements [{policy_citation}]."
                    )
            return " ".join(sentences) if sentences else None

        if remaining_core_codes:
            remaining_core_count = planning_context.get("remaining_requirement_count") or len(remaining_core_codes)
            remaining_core_credits = planning_context.get("remaining_credits")
            credit_text = (
                f" totaling {remaining_core_credits} credits"
                if isinstance(remaining_core_credits, int) and remaining_core_credits > 0
                else ""
            )
            sentences.append(
                f"Within the retrieved structured program profile, you still have {remaining_core_count} "
                f"unmet core course{'s' if remaining_core_count != 1 else ''}{credit_text}: "
                + self._join_items(remaining_core_codes)
                + " [planning_context]."
            )

        if choose_three_remaining_count:
            sentences.append(
                f"You still need {choose_three_remaining_count} course"
                + ("s" if choose_three_remaining_count != 1 else "")
                + " from the Choose Three requirement [planning_context]."
            )
            if choose_three_options:
                sentences.append(
                    "Current Choose Three options include "
                    + self._join_items(choose_three_options)
                    + " [planning_context]."
                )

        remaining_elective_credits = planning_context.get("remaining_elective_credits")
        if remaining_elective_credits:
            sentences.append(
                f"You still need {remaining_elective_credits} elective credits [planning_context]."
            )

        remaining_required_cognates = planning_context.get("remaining_required_cognate_course_codes", [])
        if remaining_required_cognates:
            sentences.append(
                "Remaining required cognate courses are "
                + self._join_items(remaining_required_cognates)
                + " [planning_context]."
            )

        if planning_context.get("statistics_requirement_remaining"):
            stats = planning_context.get("statistics_option_codes", [])
            if stats:
                sentences.append(
                    "You still need one statistics cognate from "
                    + self._join_items(stats)
                    + " [planning_context]."
                )

        if planning_context.get("science_requirement_remaining"):
            sciences = planning_context.get("science_option_codes", [])
            if sciences:
                sentences.append(
                    "You still need one science cognate from "
                    + self._join_items(sciences)
                    + " [planning_context]."
                )

        if planning_context.get("choose_one_requirement_remaining"):
            choose_one = planning_context.get("choose_one_option_codes", [])
            if choose_one:
                sentences.append(
                    "You still need one course from "
                    + self._join_items(choose_one)
                    + " [planning_context]."
                )

        sentences.append(
            "This summary does not validate prerequisite sequencing, term availability, or a full "
            "university degree audit [planning_context]."
        )

        if policy_citation:
            if self._chunk_mentions_grade_policy(retrieved_chunks, policy_citation):
                sentences.append(
                    f"No grade lower than C- may be counted toward major or cognate requirements [{policy_citation}]."
                )
            if self._chunk_mentions_andrews_core(retrieved_chunks, policy_citation):
                sentences.append(
                    f"You still need to satisfy the Andrews Core Experience requirements [{policy_citation}]."
                )

        return " ".join(sentences) if sentences else None

    def _select_model_for_question(
        self,
        *,
        normalized_question: str,
        grounded_planning_question: bool,
    ) -> str:
        planning_model = getattr(self.llm, "planning_model", None)
        if planning_model and (
            grounded_planning_question or self._is_audit_question(normalized_question)
        ):
            return planning_model
        return self.llm.model

    def _is_audit_question(self, normalized_question: str) -> bool:
        if any(keyword in normalized_question for keyword in AUDIT_KEYWORDS):
            return True
        if "still need" in normalized_question:
            return True
        if "left" in normalized_question and any(
            token in normalized_question
            for token in ("course", "courses", "requirement", "requirements", "major", "program", "degree")
        ):
            return True
        return False

    def _should_scope_retrieval_to_student_program(self, normalized_question: str) -> bool:
        if any(keyword in normalized_question for keyword in PROGRAM_EXPLORATION_KEYWORDS):
            return False
        if "switch" in normalized_question and ("major" in normalized_question or "program" in normalized_question):
            return False
        if "change" in normalized_question and ("major" in normalized_question or "program" in normalized_question):
            return False
        return True

    def _join_items(self, items: list[str]) -> str:
        values = [str(item).strip() for item in items if str(item).strip()]
        if not values:
            return ""
        if len(values) == 1:
            return values[0]
        if len(values) == 2:
            return f"{values[0]} and {values[1]}"
        return ", ".join(values[:-1]) + f", and {values[-1]}"

    def _verify_or_rewrite(
        self,
        *,
        question: str,
        initial_result: dict,
        retrieved_chunks: list[dict],
        student: dict | None,
        planning_context: dict | None,
        planning_grounding_summary: str | None = None,
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
            planning_grounding_summary=planning_grounding_summary,
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

    def _has_substantive_answer_text(self, answer: str) -> bool:
        for sentence in split_sentences(answer):
            visible_text = strip_citations(re.sub(r"\s+", " ", sentence.strip()))
            if re.search(r"[a-z0-9]", visible_text.lower()):
                return True
        return False

    def _policy_citation_id(self, planning_context: dict, retrieved_chunks: list[dict]) -> str | None:
        derived_ids = planning_context.get("derived_from_chunk_ids", [])
        if derived_ids:
            return derived_ids[0]
        return retrieved_chunks[0]["chunkId"] if retrieved_chunks else None

    def _chunk_mentions_grade_policy(self, retrieved_chunks: list[dict], chunk_id: str) -> bool:
        chunk = next((row for row in retrieved_chunks if row["chunkId"] == chunk_id), None)
        if not chunk:
            return False
        text = (chunk.get("chunk") or "").lower()
        return "no grade lower than c-" in text

    def _chunk_mentions_andrews_core(self, retrieved_chunks: list[dict], chunk_id: str) -> bool:
        chunk = next((row for row in retrieved_chunks if row["chunkId"] == chunk_id), None)
        if not chunk:
            return False
        text = (chunk.get("chunk") or "").lower()
        return "andrews core experience" in text

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
                    key: row.get(key)
                    for key in ("code", "title", "credits", "category", "rationale")
                    if row.get(key) is not None
                }
                for row in rows[:limit]
            ]

        return {
            "program": planning_context["program"],
            "bulletin_year": planning_context["bulletin_year"],
            "scope_note": planning_context.get("scope_note"),
            "completed_course_codes": planning_context.get("completed_course_codes", [])[:12],
            "completed_courses": compact_courses(
                planning_context.get("completed_courses", []),
                12,
            ),
            "completed_credits": planning_context.get("completed_credits"),
            "in_progress_course_codes": planning_context.get("in_progress_course_codes", [])[:8],
            "in_progress_credits": planning_context.get("in_progress_credits"),
            "planned_course_codes": planning_context.get("planned_course_codes", [])[:8],
            "planned_credits": planning_context.get("planned_credits"),
            "remaining_requirement_count": planning_context.get("remaining_requirement_count"),
            "remaining_credits": planning_context.get("remaining_credits"),
            "remaining_core_course_codes": planning_context.get("remaining_core_course_codes", [])[:12],
            "remaining_core_courses": compact_courses(
                planning_context.get("remaining_core_courses", []),
                12,
            ),
            "choose_three_remaining_count": planning_context.get("choose_three_remaining_count"),
            "choose_three_remaining_option_codes": [
                row.get("code")
                for row in planning_context.get("choose_three_remaining_options", [])[:8]
                if row.get("code")
            ],
            "choose_three_remaining_options": compact_courses(
                planning_context.get("choose_three_remaining_options", []),
                8,
            ),
            "remaining_elective_credits": planning_context.get("remaining_elective_credits"),
            "remaining_required_cognate_course_codes": planning_context.get(
                "remaining_required_cognate_course_codes",
                [],
            )[:8],
            "remaining_required_cognate_courses": compact_courses(
                planning_context.get("remaining_required_cognate_courses", []),
                8,
            ),
            "statistics_requirement_remaining": planning_context.get("statistics_requirement_remaining"),
            "statistics_option_codes": planning_context.get("statistics_option_codes", [])[:8],
            "statistics_options": compact_courses(
                planning_context.get("statistics_options", []),
                8,
            ),
            "science_requirement_remaining": planning_context.get("science_requirement_remaining"),
            "science_option_codes": planning_context.get("science_option_codes", [])[:8],
            "science_options": compact_courses(
                planning_context.get("science_options", []),
                8,
            ),
            "choose_one_requirement_remaining": planning_context.get("choose_one_requirement_remaining"),
            "choose_one_option_codes": planning_context.get("choose_one_option_codes", [])[:8],
            "choose_one_options": compact_courses(
                planning_context.get("choose_one_options", []),
                8,
            ),
            "recommended_next_courses": compact_courses(
                planning_context.get("recommended_next_courses", []),
                4,
            ),
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
        planning_grounding_summary: str | None,
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
                "course history, derived remaining requirements, and current registrations. Use "
                "the derived planning fields as the primary basis for audit/planning conclusions, "
                "and use bulletin chunks to support requirement or policy details."
            )
            lines.append(
                "Facts from computed planning summaries in this context, such as remaining-course "
                "lists and recommended next courses, may be cited as [planning_context]."
            )
        if planning_grounding_summary:
            lines.append("Derived planning grounding summary:")
            lines.append(planning_grounding_summary)
            lines.append(
                "Use this derived summary as grounded context for audit/planning answers. You may "
                "rephrase it, but do not contradict it, and prefer its course lists, counts, and "
                "scope limits when deciding what remains or what to recommend next."
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
            "scope_note": planning_context.get("scope_note"),
            "derived_from_chunk_ids": planning_context.get("derived_from_chunk_ids", []),
            "remaining_requirement_count": planning_context.get("remaining_requirement_count"),
            "remaining_credits": planning_context.get("remaining_credits"),
            "remaining_core_course_codes": planning_context.get("remaining_core_course_codes", []),
            "remaining_core_courses": planning_context.get("remaining_core_courses", []),
            "choose_three_remaining_count": planning_context.get("choose_three_remaining_count"),
            "choose_three_remaining_options": planning_context.get("choose_three_remaining_options", []),
            "remaining_elective_credits": planning_context.get("remaining_elective_credits"),
            "remaining_required_cognate_course_codes": planning_context.get(
                "remaining_required_cognate_course_codes",
                [],
            ),
            "remaining_required_cognate_courses": planning_context.get(
                "remaining_required_cognate_courses",
                [],
            ),
            "statistics_requirement_remaining": planning_context.get("statistics_requirement_remaining"),
            "statistics_option_codes": planning_context.get("statistics_option_codes", []),
            "statistics_options": planning_context.get("statistics_options", []),
            "science_requirement_remaining": planning_context.get("science_requirement_remaining"),
            "science_option_codes": planning_context.get("science_option_codes", []),
            "science_options": planning_context.get("science_options", []),
            "choose_one_requirement_remaining": planning_context.get("choose_one_requirement_remaining"),
            "choose_one_option_codes": planning_context.get("choose_one_option_codes", []),
            "choose_one_options": planning_context.get("choose_one_options", []),
            "recommended_next_courses": planning_context.get("recommended_next_courses", []),
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
