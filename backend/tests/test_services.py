import unittest
import sys
from unittest.mock import Mock, patch
from pathlib import Path
import socket

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.planning_service import build_planning_context, is_planning_question
from services.query_service import QueryService, build_citation_payload
from services.retrieval_service import DEFAULT_QUERY_SOURCE_TYPES
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
        self.assertEqual(context["in_progress_course_codes"], ["CPTR 276"])
        self.assertEqual([row["code"] for row in context["in_progress_courses"]], ["CPTR 276"])
        self.assertIn(
            "No class meeting-time schedule is stored yet, so this planner cannot check time conflicts.",
            context["context_gaps"],
        )
        self.assertIn(
            "No structured degree-audit rules are configured, so course recommendations must be inferred from retrieved bulletin evidence and the saved course history.",
            context["context_gaps"],
        )


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
            response["citations"][0]["pdfPageUrl"],
            "/api/bulletins/pdf/Bulletin_23-24.pdf#page=479",
        )
        self.assertEqual(
            response["retrieved_chunks"][0]["pdfPageLinks"][1]["url"],
            "/api/bulletins/pdf/Bulletin_23-24.pdf#page=480",
        )

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

    def test_generate_answer_retries_after_invalid_json_error(self):
        service = object.__new__(QueryService)
        service.llm = Mock()
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


class LLMClientTests(unittest.TestCase):
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
