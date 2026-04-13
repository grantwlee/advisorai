import unittest
import sys
from unittest.mock import Mock, patch
from pathlib import Path
import socket

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.planning_service import (
    build_deterministic_audit,
    build_planning_context,
    is_audit_question,
    is_planning_question,
    render_deterministic_audit_answer,
)
from services.query_service import QueryService, build_citation_payload
from services.retrieval_service import DEFAULT_QUERY_SOURCE_TYPES, RetrievalService
from services.llm_client import LLMError, OllamaClient
from services.verification import extract_citation_ids, verify_answer


class VerificationTests(unittest.TestCase):
    def test_extract_citation_ids_handles_multiple_ids(self):
        self.assertEqual(
            extract_citation_ids("Sentence [23-24:001, 23-24:002]."),
            ["23-24:001", "23-24:002"],
        )

    def test_verify_answer_rejects_missing_year_qualification(self):
        retrieved = [
            {
                "chunkId": "22-23:001934",
                "bulletin": "22-23",
                "pageOccurrence": [459],
                "preview": "Information Systems BBA",
                "chunk": "Information Systems BBA Total Credits - 124",
            },
            {
                "chunkId": "24-25:002860",
                "bulletin": "24-25",
                "pageOccurrence": [7],
                "preview": "Computer Science BS",
                "chunk": "Computer Science BS Total Credits - 120",
            },
        ]
        result = verify_answer(
            "The programs changed in total credits [22-23:001934, 24-25:002860].",
            retrieved,
        )
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("multiple bulletin years" in issue.lower() for issue in result["issues"])
        )

    def test_verify_answer_accepts_planning_context_citation(self):
        result = verify_answer(
            "You have completed 3 courses and are currently taking 1 course in your Computer Science program [planning_context].",
            [],
            planning_context={
                "program": "Computer Science",
                "bulletin_year": "2023-2024",
                "completed_course_codes": ["CPTR 151", "CPTR 152", "CPTR 230"],
                "in_progress_course_codes": ["CPTR 276"],
                "planned_course_codes": [],
                "completed_credits": 9,
                "in_progress_credits": 3,
                "planned_credits": 0,
                "in_progress_courses": [{"code": "CPTR 276", "title": "Data Structures and Algorithms", "credits": 3}],
                "planned_courses": [],
            },
        )

        self.assertTrue(result["passed"])

    def test_verify_answer_rejects_citation_only_sentence(self):
        retrieved = [
            {
                "chunkId": "23-24:000579",
                "bulletin": "23-24",
                "pageOccurrence": [479],
                "preview": "Computer Science BS",
                "chunk": "Computer Science BS total credits 120",
            }
        ]

        result = verify_answer(
            "Computer Science requires 120 credits [23-24:000579]. [23-24:000579]",
            retrieved,
        )

        self.assertFalse(result["passed"])
        self.assertTrue(any("only citations" in issue.lower() for issue in result["issues"]))


class PlanningServiceTests(unittest.TestCase):
    def test_is_planning_question_detects_next_semester_language(self):
        self.assertTrue(is_planning_question("What should I take next semester?"))

    def test_is_audit_question_detects_remaining_requirement_language(self):
        self.assertTrue(is_audit_question("What do I have left?"))
        self.assertTrue(is_audit_question("What courses do I still need for my major?"))

    def test_build_planning_context_uses_saved_course_history(self):
        student = {
            "student_id": "S1001",
            "name": "Alex Johnson",
            "program": "Computer Science",
            "bulletin_year": "2023-2024",
            "courses": [
                {
                    "status": "completed",
                    "course": {"code": "CPTR 151", "credits": 3},
                },
                {
                    "status": "completed",
                    "course": {"code": "CPTR 152", "credits": 3},
                },
                {
                    "status": "completed",
                    "course": {"code": "CPTR 230", "credits": 3},
                },
                {
                    "status": "in_progress",
                    "course": {"code": "CPTR 276", "credits": 3},
                },
            ],
        }

        context = build_planning_context(student)

        self.assertIsNotNone(context)
        self.assertEqual(context["completed_course_codes"], ["CPTR 151", "CPTR 152", "CPTR 230"])
        self.assertEqual([row["code"] for row in context["completed_courses"]], ["CPTR 151", "CPTR 152", "CPTR 230"])
        self.assertEqual(context["in_progress_course_codes"], ["CPTR 276"])
        self.assertEqual([row["code"] for row in context["in_progress_courses"]], ["CPTR 276"])
        self.assertIn(
            "No class meeting-time schedule is stored yet, so this planner cannot check time conflicts.",
            context["context_gaps"],
        )
        self.assertIn(
            "Deterministic audit is currently limited to structured program-profile requirements and saved course history; full university degree-audit rules are not yet configured.",
            context["context_gaps"],
        )

    def test_build_deterministic_audit_extracts_remaining_requirements_from_program_profile(self):
        planning_context = {
            "program": "Computer Science",
            "bulletin_year": "2023-2024",
            "completed_course_codes": ["CPTR 151", "CPTR 152", "CPTR 230"],
            "completed_courses": [
                {"code": "CPTR 151", "title": "Computer Science I", "credits": 3},
                {"code": "CPTR 152", "title": "Computer Science II", "credits": 3},
                {"code": "CPTR 230", "title": "Data Science Fundamentals", "credits": 3},
            ],
            "in_progress_course_codes": ["CPTR 276"],
            "planned_course_codes": [],
            "in_progress_courses": [{"code": "CPTR 276", "title": "Data Structures and Algorithms", "credits": 3}],
            "planned_courses": [],
        }
        retrieved_chunks = [
            {
                "chunkId": "23-24:000579",
                "structuredData": {
                    "program": {
                        "program": "Computer Science BS",
                        "sections": [
                            {
                                "section": "Core Courses",
                                "type": "required_courses",
                                "required_credits": "42",
                                "courses": [
                                    {"course": "CPTR 151", "title": "Computer Science I", "credits": "3"},
                                    {"course": "CPTR 152", "title": "Computer Science II", "credits": "3"},
                                    {"course": "CPTR 230", "title": "Data Science Fundamentals", "credits": "3"},
                                    {"course": "CPTR 276", "title": "Data Structures and Algorithms", "credits": "3"},
                                    {"course": "CPTR 425", "title": "Programming Languages", "credits": "3"},
                                    {"course": "CPTR 430", "title": "Analysis of Algorithms", "credits": "3"},
                                ],
                            },
                            {
                                "section": "Choose Three Courses",
                                "type": "choose_from_pool",
                                "required_credits": "9",
                                "options": [
                                    {"course": "CPTR 251", "title": "Server Application Development", "credits": "3"},
                                    {"course": "CPTR 252", "title": "Mobile Application Development", "credits": "3"},
                                    {"course": "INFS 330", "title": "Introduction to Web Development", "credits": "3"},
                                ],
                            },
                            {
                                "section": "Cognates - Required",
                                "type": "required_courses",
                                "courses": [
                                    {"course": "MATH 191", "title": "Calculus I", "credits": "4"},
                                    {"course": "MATH 192", "title": "Calculus II", "credits": "4"},
                                ],
                            },
                            {
                                "section": "Cognates - Statistics Choose At Least One",
                                "type": "choose_from_pool",
                                "options": [
                                    {"course": "STAT 285", "title": "Introduction to Applied Statistics", "credits": "3"},
                                    {"course": "STAT 340", "title": "Probability Theory with Statistical Applications", "credits": "3"},
                                ],
                            },
                            {
                                "section": "Electives",
                                "type": "choose_from_pool",
                                "rules": [
                                    "Choose 15 credits in consultation with academic advisor from CPTR courses, INFS",
                                    "310, INFS 330, and INFS 436 that have not already been taken to satisfy the major",
                                    "core requirements.",
                                    "Up to 6 credits of the following courses may be substituted for CPTR elective",
                                    "credits.",
                                    "MATH 240, 286, 426",
                                    "STAT 340",
                                    "ENGR 225, 275, 310, 415",
                                ],
                            },
                        ],
                        "other_requirements": [
                            "No grade lower than C- may be counted toward major or cognate requirements.",
                            "Students must fulfill all Bachelor's Degree requirements listed in the Andrews Core Experience.",
                        ],
                    }
                },
            }
        ]

        audit = build_deterministic_audit(
            planning_context=planning_context,
            retrieved_chunks=retrieved_chunks,
        )

        self.assertIsNotNone(audit)
        self.assertEqual(audit["citation_chunk_id"], "23-24:000579")
        rendered = render_deterministic_audit_answer(audit)
        self.assertIn("You have completed CPTR 151, CPTR 152, and CPTR 230 [planning_context].", rendered)
        self.assertIn("You are currently taking CPTR 276 [planning_context].", rendered)
        self.assertIn("CPTR 425 and CPTR 430", rendered)
        self.assertIn("You still need three courses from Choose Three Courses", rendered)
        self.assertIn("MATH 191 and MATH 192", rendered)
        self.assertIn("one statistics cognate", rendered)
        self.assertIn(
            "Up to 6 of those elective credits may instead come from MATH 240, MATH 286, MATH 426, STAT 340, ENGR 225, ENGR 275, ENGR 310, and ENGR 415",
            rendered,
        )
        self.assertIn("Andrews Core Experience", rendered)


class QueryServiceTests(unittest.TestCase):
    def test_build_citation_payload_includes_pdf_page_links(self):
        citations = build_citation_payload(
            "Computer Science requires 120 credits [23-24:009001].",
            [
                {
                    "chunkId": "23-24:009001",
                    "bulletin": "23-24",
                    "pageOccurrence": [479, 480],
                    "sourcePageOccurrence": [479, 480],
                    "preview": "Program Summary: Computer Science BS",
                    "chunk": "Program Summary: Computer Science BS\nTotal Credits - 120",
                    "sourcePdf": "Bulletin_23-24.pdf",
                    "sourceType": "program_summary",
                    "program": "Computer Science BS",
                    "sectionTitle": "Computer Science BS",
                }
            ],
        )

        self.assertEqual(citations[0]["pdfUrl"], "/api/bulletins/pdf/Bulletin_23-24.pdf")
        self.assertEqual(
            citations[0]["pdfPageUrl"],
            "/api/bulletins/pdf/Bulletin_23-24.pdf#page=479",
        )
        self.assertEqual(
            citations[0]["pdfPageLinks"],
            [
                {
                    "page": 479,
                    "url": "/api/bulletins/pdf/Bulletin_23-24.pdf#page=479",
                },
                {
                    "page": 480,
                    "url": "/api/bulletins/pdf/Bulletin_23-24.pdf#page=480",
                },
            ],
        )
        self.assertEqual(
            citations[0]["chunk"],
            "Program Summary: Computer Science BS\nTotal Credits - 120",
        )

    @patch("services.query_service.get_student_payload")
    def test_answer_question_retrieves_summary_chunks_only(self, mock_get_student_payload):
        service = object.__new__(QueryService)
        service.retrieval = Mock()
        service.llm = Mock()
        service._generate_answer = Mock(
            return_value={
                "status": "answered",
                "answer": "Computer Science requires 120 credits [23-24:009001].",
                "refusal_reason": None,
            }
        )
        service._verify_or_rewrite = Mock(
            return_value={
                "status": "answered",
                "answer": "Computer Science requires 120 credits [23-24:009001].",
                "verifier": {"passed": True, "issues": []},
            }
        )
        service._log_event = Mock()

        mock_get_student_payload.return_value = {
            "student_id": "S1001",
            "name": "Alex Johnson",
            "program": "Computer Science",
            "bulletin_year": "2023-2024",
            "courses": [],
        }
        service.retrieval.hybrid_search.return_value = [
            {
                "chunkId": "23-24:009001",
                "bulletin": "23-24",
                "pageOccurrence": [479, 480],
                "sourcePageOccurrence": [479, 480],
                "sourceChunkIds": ["23-24:007640", "23-24:007641"],
                "preview": "Program Summary: Computer Science BS",
                "chunk": "Program Summary: Computer Science BS\nTotal Credits - 120",
                "sourcePdf": "Bulletin_23-24.pdf",
                "sourceType": "program_summary",
                "program": "Computer Science BS",
                "sectionTitle": "Computer Science BS",
                "score": 5.0,
            }
        ]

        response = service.answer_question(
            question="What do I have left?",
            student_id="S1001",
            top_k=4,
        )

        service.retrieval.hybrid_search.assert_called_once_with(
            "What do I have left?",
            k=1,
            bulletin_year="2023-2024",
            program="Computer Science",
            source_types=DEFAULT_QUERY_SOURCE_TYPES,
        )
        self.assertEqual(response["status"], "answered")
        self.assertEqual(response["student_context"]["student_id"], "S1001")
        self.assertEqual(response["citations"][0]["sourceType"], "program_summary")
        self.assertEqual(
            response["citations"][0]["chunk"],
            "Program Summary: Computer Science BS\nTotal Credits - 120",
        )
        self.assertEqual(
            response["citations"][0]["pdfPageUrl"],
            "/api/bulletins/pdf/Bulletin_23-24.pdf#page=479",
        )
        self.assertEqual(
            response["retrieved_chunks"][0]["pdfPageLinks"][1]["url"],
            "/api/bulletins/pdf/Bulletin_23-24.pdf#page=480",
        )

    @patch("services.query_service.get_student_payload")
    def test_answer_question_uses_deterministic_audit_for_audit_questions(self, mock_get_student_payload):
        service = object.__new__(QueryService)
        service.retrieval = Mock()
        service.llm = Mock()
        service._log_event = Mock()

        mock_get_student_payload.return_value = {
            "student_id": "S1001",
            "name": "Alex Johnson",
            "program": "Computer Science",
            "bulletin_year": "2023-2024",
            "courses": [
                {"status": "completed", "course": {"code": "CPTR 151", "title": "Computer Science I", "credits": 3}},
                {"status": "completed", "course": {"code": "CPTR 152", "title": "Computer Science II", "credits": 3}},
                {"status": "completed", "course": {"code": "CPTR 230", "title": "Data Science Fundamentals", "credits": 3}},
                {"status": "in_progress", "course": {"code": "CPTR 276", "title": "Data Structures and Algorithms", "credits": 3}},
            ],
        }
        service.retrieval.hybrid_search.return_value = [
            {
                "chunkId": "23-24:000579",
                "bulletin": "23-24",
                "pageOccurrence": [479],
                "sourcePageOccurrence": [479],
                "sourceChunkIds": [],
                "preview": "Program Profile: Computer Science BS",
                "chunk": "Program Profile: Computer Science BS\nCore Courses: CPTR 151, CPTR 152, CPTR 230, CPTR 276, CPTR 425",
                "sourcePdf": "Bulletin_23-24.pdf",
                "sourceType": "program_summary",
                "program": "Computer Science BS",
                "sectionTitle": "Computer Science BS",
                "sectionType": "program_profile",
                "score": 5.0,
                "structuredData": {
                    "program": {
                        "program": "Computer Science BS",
                        "sections": [
                            {
                                "section": "Core Courses",
                                "type": "required_courses",
                                "courses": [
                                    {"course": "CPTR 151", "title": "Computer Science I", "credits": "3"},
                                    {"course": "CPTR 152", "title": "Computer Science II", "credits": "3"},
                                    {"course": "CPTR 230", "title": "Data Science Fundamentals", "credits": "3"},
                                    {"course": "CPTR 276", "title": "Data Structures and Algorithms", "credits": "3"},
                                    {"course": "CPTR 425", "title": "Programming Languages", "credits": "3"},
                                ],
                            }
                        ],
                        "other_requirements": [],
                    }
                },
            }
        ]

        response = service.answer_question(
            question="What do I have left?",
            student_id="S1001",
        )

        self.assertEqual(response["status"], "answered")
        self.assertIn("CPTR 425", response["answer"])
        self.assertIn("[planning_context]", response["answer"])
        self.assertEqual(response["timings_ms"]["generation"], 0)
        self.assertIsNotNone(response["audit_summary"])
        service.llm.generate_json.assert_not_called()

    def test_repair_answer_citations_adds_supporting_chunk_id(self):
        service = object.__new__(QueryService)
        retrieved = [
            {
                "chunkId": "23-24:007600",
                "bulletin": "23-24",
                "chunk": (
                    "Computer Science BS students follow the 2023-2024 bulletin "
                    "requirements for their degree plan."
                ),
                "score": 2.3,
            }
        ]

        repaired = service._repair_answer_citations(
            "Computer Science students follow the 2023-2024 bulletin requirements.",
            retrieved,
            None,
        )

        self.assertIn("[23-24:007600]", repaired)
        verified = verify_answer(repaired, retrieved)
        self.assertTrue(verified["passed"])

    def test_repair_answer_citations_can_use_planning_context(self):
        service = object.__new__(QueryService)
        repaired = service._repair_answer_citations(
            "You have completed 3 courses and are currently taking 1 course in your Computer Science program.",
            [],
            {
                "program": "Computer Science",
                "bulletin_year": "2023-2024",
                "completed_course_codes": ["CPTR 151", "CPTR 152", "CPTR 230"],
                "in_progress_course_codes": ["CPTR 276"],
                "planned_course_codes": [],
                "completed_credits": 9,
                "in_progress_credits": 3,
                "planned_credits": 0,
                "in_progress_courses": [{"code": "CPTR 276", "title": "Data Structures and Algorithms", "credits": 3}],
                "planned_courses": [],
            },
        )

        self.assertIn("[planning_context]", repaired)
        verified = verify_answer(
            repaired,
            [],
            planning_context={
                "program": "Computer Science",
                "bulletin_year": "2023-2024",
                "completed_course_codes": ["CPTR 151", "CPTR 152", "CPTR 230"],
                "in_progress_course_codes": ["CPTR 276"],
                "planned_course_codes": [],
                "completed_credits": 9,
                "in_progress_credits": 3,
                "planned_credits": 0,
                "in_progress_courses": [{"code": "CPTR 276", "title": "Data Structures and Algorithms", "credits": 3}],
                "planned_courses": [],
            },
        )
        self.assertTrue(verified["passed"])

    def test_normalize_answer_removes_citation_only_sentence(self):
        service = object.__new__(QueryService)

        normalized = service._normalize_answer(
            "Computer Science requires 120 credits [23-24:000579]. [23-24:000579]"
        )

        self.assertEqual(normalized, "Computer Science requires 120 credits [23-24:000579].")

    def test_prompt_ready_chunks_include_full_chunk_payload(self):
        service = object.__new__(QueryService)
        retrieved = [
            {
                "chunkId": "23-24:007677",
                "bulletin": "23-24",
                "pageOccurrence": [487],
                "chunk": "A" * 4000,
            }
        ]

        prompt_chunks = service._prompt_ready_chunks(retrieved)

        self.assertEqual(len(prompt_chunks), 1)
        self.assertEqual(prompt_chunks[0]["recordType"], "bulletin_requirement_evidence")
        self.assertEqual(
            prompt_chunks[0]["evidenceLabel"],
            "course_requirements_and_bulletin_rules",
        )
        self.assertEqual(prompt_chunks[0]["chunkId"], "23-24:007677")
        self.assertEqual(prompt_chunks[0]["text"], "A" * 4000)

    def test_prompt_ready_chunks_use_chunk_text_for_program_profiles(self):
        service = object.__new__(QueryService)
        retrieved = [
            {
                "chunkId": "23-24:007678",
                "bulletin": "23-24",
                "pageOccurrence": [479],
                "chunk": "Program Profile: Computer Science BS\nTotal Credits - 120",
                "structuredData": {
                    "kind": "program_profile",
                    "program": {"program": "Computer Science BS", "summary": {"total_credits": "120"}},
                },
            }
        ]

        prompt_chunks = service._prompt_ready_chunks(retrieved)

        self.assertEqual(prompt_chunks[0]["text"], "Program Profile: Computer Science BS\nTotal Credits - 120")

    def test_build_prompt_separates_bulletin_requirement_evidence_from_student_context(self):
        service = object.__new__(QueryService)

        prompt = service._build_prompt(
            question="What do I have left?",
            student={
                "student_id": "S1001",
                "name": "Alex Johnson",
                "program": "Computer Science",
                "bulletin_year": "2023-2024",
            },
            planning_context={
                "program": "Computer Science",
                "bulletin_year": "2023-2024",
                "completed_course_codes": ["CPTR 151"],
                "in_progress_course_codes": [],
                "planned_course_codes": [],
                "in_progress_courses": [],
                "planned_courses": [],
            },
            retrieved_chunks=[
                {
                    "chunkId": "23-24:007678",
                    "bulletin": "23-24",
                    "pageOccurrence": [479],
                    "programPageOccurrence": [479],
                    "chunk": "Program Profile: Computer Science BS\nTotal Credits - 120",
                    "sourceType": "program_summary",
                    "program": "Computer Science BS",
                    "sectionTitle": "Computer Science BS",
                    "sectionType": "program_profile",
                    "sourceChunkIds": [],
                    "structuredData": {"kind": "program_profile"},
                }
            ],
            rewrite_feedback=None,
            prior_answer=None,
        )

        self.assertIn("Structured planning context:", prompt)
        self.assertIn("Bulletin requirement evidence:", prompt)
        self.assertIn(
            "Everything in this section is bulletin-derived requirement evidence",
            prompt,
        )
        self.assertIn("\"recordType\": \"bulletin_requirement_evidence\"", prompt)

    def test_generate_answer_retries_after_invalid_json_error(self):
        service = object.__new__(QueryService)
        service.llm = Mock()
        service.llm.build_generate_payload.side_effect = (
            lambda *, system_prompt, prompt, temperature=0.1: {
                "model": "test-model",
                "system": system_prompt,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": 180,
                    "num_ctx": 4096,
                },
            }
        )
        service.llm.generate_json.side_effect = [
            LLMError("LLM returned invalid JSON: {bad"),
            {"status": "answered", "answer": "Answer [23-24:000001].", "refusal_reason": None},
        ]

        result = service._generate_answer(
            question="What do I have left?",
            retrieved_chunks=[{"chunkId": "23-24:000001", "bulletin": "23-24", "chunk": "Program Profile"}],
            student=None,
            planning_context=None,
        )

        self.assertEqual(result["status"], "answered")
        self.assertEqual(service.llm.generate_json.call_count, 2)

    def test_generate_answer_retries_after_invalid_schema(self):
        service = object.__new__(QueryService)
        service.llm = Mock()
        service.llm.build_generate_payload.side_effect = (
            lambda *, system_prompt, prompt, temperature=0.1: {
                "model": "test-model",
                "system": system_prompt,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": 180,
                    "num_ctx": 4096,
                },
            }
        )
        service.llm.generate_json.side_effect = [
            {"status": "accepted", "answer": {"programs": []}, "refusal_reason": None},
            {"status": "answered", "answer": "Answer [23-24:000001].", "refusal_reason": None},
        ]

        result = service._generate_answer(
            question="What do I have left?",
            retrieved_chunks=[{"chunkId": "23-24:000001", "bulletin": "23-24", "chunk": "Program Profile"}],
            student=None,
            planning_context=None,
        )

        self.assertEqual(result["status"], "answered")
        self.assertEqual(service.llm.generate_json.call_count, 2)

    @patch("services.query_service.get_student_payload")
    def test_answer_question_can_include_exact_prompt_debug_payload(self, mock_get_student_payload):
        service = object.__new__(QueryService)
        service.retrieval = Mock()
        service.llm = Mock()
        service.llm.build_generate_payload.side_effect = (
            lambda *, system_prompt, prompt, temperature=0.1: {
                "model": "test-model",
                "system": system_prompt,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": 180,
                    "num_ctx": 4096,
                },
            }
        )
        service.llm.generate_json.return_value = {
            "status": "answered",
            "answer": "Computer Science requires 120 credits [23-24:009001].",
            "refusal_reason": None,
        }
        service._log_event = Mock()

        mock_get_student_payload.return_value = {
            "student_id": "S1001",
            "name": "Alex Johnson",
            "program": "Computer Science",
            "bulletin_year": "2023-2024",
            "courses": [],
        }
        service.retrieval.hybrid_search.return_value = [
            {
                "chunkId": "23-24:009001",
                "bulletin": "23-24",
                "pageOccurrence": [479],
                "sourcePageOccurrence": [479],
                "sourceChunkIds": ["23-24:007640"],
                "preview": "Program Summary: Computer Science BS",
                "chunk": "Program Summary: Computer Science BS\nTotal Credits - 120",
                "sourcePdf": "Bulletin_23-24.pdf",
                "sourceType": "program_summary",
                "program": "Computer Science BS",
                "sectionTitle": "Computer Science BS",
                "score": 5.0,
            }
        ]

        response = service.answer_question(
            question="What do I have left?",
            student_id="S1001",
            include_prompt_debug=True,
        )

        self.assertIn("prompt_debug", response)
        self.assertEqual(len(response["prompt_debug"]["attempts"]), 1)
        attempt = response["prompt_debug"]["attempts"][0]
        self.assertEqual(attempt["stage"], "initial_answer")
        self.assertEqual(attempt["attempt"], 1)
        self.assertEqual(attempt["variant"], "primary")
        self.assertEqual(
            attempt["request_payload"]["system"],
            attempt["system_prompt"],
        )
        self.assertEqual(
            attempt["request_payload"]["prompt"],
            attempt["prompt"],
        )
        logged_response = service._log_event.call_args.args[0]
        self.assertEqual(logged_response["prompt_debug"], response["prompt_debug"])

    def test_log_event_includes_prompt_debug_when_present(self):
        service = object.__new__(QueryService)

        with patch("services.query_service.LOG_PATH") as mock_log_path:
            handle = mock_log_path.open.return_value.__enter__.return_value
            service._log_event(
                {
                    "status": "answered",
                    "refusal_reason": None,
                    "retrieved_chunks": [],
                    "citations": [],
                    "verifier": {"passed": True, "issues": []},
                    "timings_ms": {"total": 1},
                    "planning_context": None,
                    "prompt_debug": {
                        "attempts": [
                            {
                                "stage": "initial_answer",
                                "attempt": 1,
                                "variant": "primary",
                                "system_prompt": "Return JSON",
                                "prompt": "Hello",
                                "request_payload": {"prompt": "Hello"},
                            }
                        ]
                    },
                },
                question="Hello?",
                student=None,
            )

            written = handle.write.call_args.args[0]
        self.assertIn("\"prompt_debug\"", written)


class RetrievalServiceTests(unittest.TestCase):
    def test_row_matches_program_uses_structured_program_identity_not_chunk_mentions(self):
        service = object.__new__(RetrievalService)

        self.assertFalse(
            service._row_matches_program(
                {
                    "program": "Integrative Studies BS",
                    "sectionTitle": "Integrative Studies BS",
                    "chunk": "This text mentions computer science in passing.",
                    "structuredData": {
                        "program": {
                            "program": "Integrative Studies BS",
                        }
                    },
                },
                "Computer Science",
            )
        )
        self.assertTrue(
            service._row_matches_program(
                {
                    "program": "Computer Science BS",
                    "sectionTitle": "Computer Science BS",
                    "chunk": "Program Profile: Computer Science BS",
                    "structuredData": {
                        "program": {
                            "program": "Computer Science BS",
                        }
                    },
                },
                "Computer Science",
            )
        )

    @patch("services.retrieval_service.text", side_effect=lambda sql: sql)
    def test_keyword_search_filters_by_program_after_metadata_lookup(self, _mock_text):
        service = object.__new__(RetrievalService)
        service.metadata_by_hash = {
            "bad-hash": {
                "chunkId": "23-24:000536",
                "bulletin": "23-24",
                "chunk": "Mentions computer science somewhere in the body.",
                "program": "Integrative Studies BS",
                "sectionTitle": "Integrative Studies BS",
                "structuredData": {"program": {"program": "Integrative Studies BS"}},
            },
            "good-hash": {
                "chunkId": "23-24:000579",
                "bulletin": "23-24",
                "chunk": "Program Profile: Computer Science BS",
                "program": "Computer Science BS",
                "sectionTitle": "Computer Science BS",
                "structuredData": {"program": {"program": "Computer Science BS"}},
            },
        }

        connection = Mock()
        connection.execute.return_value.mappings.return_value.all.return_value = [
            {"chunk_hash": "bad-hash", "bulletin_year": "2023-2024", "chunk_text": "bad", "keyword_score": 9.0},
            {"chunk_hash": "good-hash", "bulletin_year": "2023-2024", "chunk_text": "good", "keyword_score": 8.0},
        ]
        connect_ctx = Mock()
        connect_ctx.__enter__ = Mock(return_value=connection)
        connect_ctx.__exit__ = Mock(return_value=False)

        with patch("services.retrieval_service.engine.connect", return_value=connect_ctx):
            results = service.keyword_search(
                "what bulletin year applies to me?",
                k=1,
                bulletin_year="2023-2024",
                program="Computer Science",
                source_types=("program_summary",),
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["chunkId"], "23-24:000579")
        self.assertEqual(results[0]["program"], "Computer Science BS")


class LLMClientTests(unittest.TestCase):
    def test_build_generate_payload_matches_ollama_request_shape(self):
        client = OllamaClient()

        payload = client.build_generate_payload(
            system_prompt="Return JSON",
            prompt="Hello",
            temperature=0.25,
        )

        self.assertEqual(payload["model"], client.model)
        self.assertEqual(payload["system"], "Return JSON")
        self.assertEqual(payload["prompt"], "Hello")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"]["temperature"], 0.25)
        self.assertEqual(payload["options"]["num_predict"], client.max_tokens)
        self.assertEqual(payload["options"]["num_ctx"], client.context_window)

    @patch("urllib.request.urlopen", side_effect=socket.timeout("timed out"))
    def test_generate_json_wraps_socket_timeout_as_llm_error(self, _mock_urlopen):
        client = OllamaClient()

        with self.assertRaises(LLMError):
            client.generate_json(
                system_prompt="Return JSON",
                prompt="Hello",
            )


if __name__ == "__main__":
    unittest.main()
