import unittest
import sys
from unittest.mock import Mock, patch
from pathlib import Path
import socket

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.planning_service import (
    build_planning_context,
    enrich_planning_context,
    is_planning_question,
)
from services.query_service import QueryService, build_citation_payload
from services.retrieval_service import DEFAULT_QUERY_SOURCE_TYPES, RetrievalService
from services.llm_client import LLMError, OllamaClient
from services.verification import extract_citation_ids, verify_answer


def _sample_student_payload() -> dict:
    return {
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


def _sample_program_profile_chunk() -> dict:
    return {
        "chunkId": "23-24:000579",
        "bulletin": "23-24",
        "pageOccurrence": [479],
        "sourcePageOccurrence": [479],
        "preview": "Program Profile: Computer Science BS",
        "chunk": (
            "Program Profile: Computer Science BS\n"
            "No grade lower than C- may be counted toward major or cognate requirements.\n"
            "Students must also satisfy the Andrews Core Experience requirements."
        ),
        "sourcePdf": "Bulletin_23-24.pdf",
        "sourceType": "program_summary",
        "program": "Computer Science BS",
        "sectionTitle": "Computer Science BS",
        "sectionType": "program_profile",
        "score": 5.0,
        "structuredData": {
            "kind": "program_profile",
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
                            {"course": "CPTR 437", "title": "Formal Theory of Computation", "credits": "3"},
                            {"course": "CPTR 440", "title": "Operating Systems", "credits": "3"},
                            {"course": "CPTR 460", "title": "Software Engineering", "credits": "3"},
                            {"course": "CPTR 487", "title": "Artificial Intelligence", "credits": "3"},
                            {"course": "INFS 428", "title": "Database Systems Design and Development", "credits": "3"},
                        ],
                    },
                    {
                        "section": "Choose Three Courses",
                        "type": "choose_from_pool",
                        "required_credits": "9",
                        "options": [
                            {"course": "CPTR 251", "title": "Server Application Development", "credits": "3"},
                            {"course": "CPTR 252", "title": "Mobile Application Development", "credits": "3"},
                            {"course": "CPTR 285", "title": "Systems Programming", "credits": "3"},
                            {"course": "CPTR 345", "title": "Virtual and Augmented Reality", "credits": "3"},
                            {"course": "INFS 330", "title": "Introduction to Web Development", "credits": "3"},
                        ],
                    },
                    {
                        "section": "Electives",
                        "type": "choose_from_pool",
                        "required_credits": "15",
                    },
                    {
                        "section": "Cognates - Required",
                        "type": "required_courses",
                        "courses": [
                            {"course": "ENGR 385", "title": "Microprocessor Systems", "credits": "4"},
                            {"course": "MATH 191", "title": "Calculus I", "credits": "4"},
                            {"course": "MATH 192", "title": "Calculus II", "credits": "4"},
                            {"course": "MATH 215", "title": "Introduction to Linear Algebra", "credits": "3"},
                            {"course": "MATH 355", "title": "Foundations of Advanced Mathematics", "credits": "3"},
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
                        "section": "Cognates - Science Choose At Least One",
                        "type": "choose_from_pool",
                        "options": [
                            {"course": "BIOL 165", "title": "Integrated Biology I", "credits": "4"},
                            {"course": "CHEM 131", "title": "General Chemistry I", "credits": "4"},
                        ],
                    },
                    {
                        "section": "Choose One Courses",
                        "type": "choose_from_pool",
                        "options": [
                            {"course": "RELT 340", "title": "Religion and Ethics in Modern Society", "credits": "3"},
                            {"course": "RELT 385", "title": "Christian Ethics", "credits": "3"},
                        ],
                    },
                ],
            },
        },
    }


class VerificationTests(unittest.TestCase):
    def test_extract_citation_ids_handles_multiple_ids(self):
        self.assertEqual(
            extract_citation_ids("Sentence [23-24:001, 23-24:002]."),
            ["23-24:001", "23-24:002"],
        )

    def test_verify_answer_accepts_single_citation_for_multiple_sentences(self):
        retrieved = [
            {
                "chunkId": "23-24:000579",
                "bulletin": "23-24",
                "pageOccurrence": [479],
                "preview": "Computer Science BS",
                "chunk": (
                    "Computer Science BS total credits 120. "
                    "Students must complete CPTR 151 and CPTR 152."
                ),
            }
        ]

        result = verify_answer(
            "Computer Science requires 120 credits. Students must complete CPTR 151 and CPTR 152 [23-24:000579].",
            retrieved,
        )

        self.assertTrue(result["passed"])

    def test_verify_answer_rejects_answer_without_any_citation(self):
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
            "Computer Science requires 120 credits.",
            retrieved,
        )

        self.assertFalse(result["passed"])
        self.assertTrue(
            any("at least one valid citation" in issue.lower() for issue in result["issues"])
        )

    def test_verify_answer_reports_empty_answer_before_citation_failure(self):
        result = verify_answer("", [])

        self.assertFalse(result["passed"])
        self.assertEqual(result["issues"], ["Answer is empty."])

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
        self.assertEqual([row["code"] for row in context["completed_courses"]], ["CPTR 151", "CPTR 152", "CPTR 230"])
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

    def test_enrich_planning_context_derives_remaining_courses_and_recommendations(self):
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
            "completed_credits": 9,
            "in_progress_credits": 3,
            "planned_credits": 0,
            "in_progress_courses": [{"code": "CPTR 276", "title": "Data Structures and Algorithms", "credits": 3}],
            "planned_courses": [],
            "context_gaps": [],
        }
        retrieved = [
            {
                "chunkId": "23-24:000579",
                "bulletin": "23-24",
                "program": "Computer Science BS",
                "sectionTitle": "Computer Science BS",
                "structuredData": {
                    "kind": "program_profile",
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
                                    {"course": "CPTR 437", "title": "Formal Theory of Computation", "credits": "3"},
                                    {"course": "CPTR 440", "title": "Operating Systems", "credits": "3"},
                                    {"course": "CPTR 460", "title": "Software Engineering", "credits": "3"},
                                    {"course": "CPTR 487", "title": "Artificial Intelligence", "credits": "3"},
                                    {"course": "INFS 428", "title": "Database Systems Design and Development", "credits": "3"},
                                ],
                            },
                            {
                                "section": "Choose Three Courses",
                                "type": "choose_from_pool",
                                "required_credits": "9",
                                "options": [
                                    {"course": "CPTR 251", "title": "Server Application Development", "credits": "3"},
                                    {"course": "CPTR 252", "title": "Mobile Application Development", "credits": "3"},
                                ],
                            },
                            {
                                "section": "Electives",
                                "type": "choose_from_pool",
                                "required_credits": "15",
                            },
                            {
                                "section": "Cognates - Required",
                                "type": "required_courses",
                                "courses": [
                                    {"course": "ENGR 385", "title": "Microprocessor Systems", "credits": "4"},
                                    {"course": "MATH 191", "title": "Calculus I", "credits": "4"},
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
                                "section": "Cognates - Science Choose At Least One",
                                "type": "choose_from_pool",
                                "options": [
                                    {"course": "PHYS 141", "title": "General Physics I", "credits": "4"},
                                ],
                            },
                            {
                                "section": "Choose One Courses",
                                "type": "choose_from_pool",
                                "options": [
                                    {"course": "RELT 340", "title": "Religion and Ethics in Modern Society", "credits": "3"},
                                ],
                            },
                        ],
                    },
                },
            }
        ]

        enriched = enrich_planning_context(planning_context, retrieved)

        self.assertEqual(enriched["remaining_requirement_count"], 7)
        self.assertEqual(enriched["remaining_credits"], 21)
        self.assertEqual(
            enriched["remaining_core_course_codes"],
            ["CPTR 425", "CPTR 430", "CPTR 437", "CPTR 440", "CPTR 460", "CPTR 487", "INFS 428"],
        )
        self.assertEqual(
            [row["code"] for row in enriched["recommended_next_courses"]],
            ["CPTR 425", "CPTR 430", "CPTR 437"],
        )
        self.assertEqual(enriched["choose_three_remaining_count"], 3)
        self.assertEqual(enriched["remaining_elective_credits"], 15)
        self.assertTrue(enriched["statistics_requirement_remaining"])


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
            k=4,
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
    def test_answer_question_does_not_scope_program_for_switch_major_questions(self, mock_get_student_payload):
        service = object.__new__(QueryService)
        service.retrieval = Mock()
        service.llm = Mock()
        service._generate_answer = Mock(
            return_value={
                "status": "answered",
                "answer": "You can compare both programs using the retrieved evidence [23-24:009001].",
                "refusal_reason": None,
            }
        )
        service._verify_or_rewrite = Mock(
            return_value={
                "status": "answered",
                "answer": "You can compare both programs using the retrieved evidence [23-24:009001].",
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
                "pageOccurrence": [479],
                "sourcePageOccurrence": [479],
                "sourceChunkIds": ["23-24:007640"],
                "preview": "Program Summary",
                "chunk": "Program Summary",
                "sourcePdf": "Bulletin_23-24.pdf",
                "sourceType": "program_summary",
                "program": "Information Systems BBA",
                "sectionTitle": "Information Systems BBA",
                "score": 5.0,
            }
        ]

        service.answer_question(
            question="Can I switch from Computer Science to Information Systems?",
            student_id="S1001",
        )

        service.retrieval.hybrid_search.assert_called_once_with(
            "Can I switch from Computer Science to Information Systems?",
            k=2,
            bulletin_year="2023-2024",
            program=None,
            source_types=DEFAULT_QUERY_SOURCE_TYPES,
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

    @patch("services.query_service.get_student_payload")
    def test_answer_question_passes_grounding_summary_to_llm_for_audit_questions(self, mock_get_student_payload):
        service = object.__new__(QueryService)
        service.retrieval = Mock()
        service.llm = Mock()
        service._generate_answer = Mock(
            return_value={
                "status": "answered",
                "answer": "You still have several remaining requirements [planning_context].",
                "refusal_reason": None,
            }
        )
        service._verify_or_rewrite = Mock(
            return_value={
                "status": "answered",
                "answer": "You still have several remaining requirements [planning_context].",
                "verifier": {"passed": True, "issues": []},
            }
        )
        service._log_event = Mock()

        mock_get_student_payload.return_value = _sample_student_payload()
        service.retrieval.hybrid_search.return_value = [_sample_program_profile_chunk()]

        response = service.answer_question(
            question="What do I have left?",
            student_id="S1001",
        )

        self.assertEqual(response["status"], "answered")
        self.assertEqual(
            response["answer"],
            "You still have several remaining requirements [planning_context].",
        )
        self.assertEqual(service._generate_answer.call_count, 1)
        self.assertIn(
            "7 unmet core courses totaling 21 credits",
            service._generate_answer.call_args.kwargs["planning_grounding_summary"],
        )

    def test_build_prompt_includes_detailed_grounding_summary_for_planning_questions(self):
        service = object.__new__(QueryService)
        planning_context = enrich_planning_context(
            build_planning_context(_sample_student_payload()),
            [_sample_program_profile_chunk()],
        )
        planning_grounding_summary = service._build_deterministic_planning_answer(
            question="What should I take next semester?",
            planning_context=planning_context,
            retrieved_chunks=[_sample_program_profile_chunk()],
        )
        prompt = service._build_prompt(
            question="What should I take next semester?",
            student=_sample_student_payload(),
            planning_context=planning_context,
            planning_grounding_summary=planning_grounding_summary,
            retrieved_chunks=[_sample_program_profile_chunk()],
            rewrite_feedback=None,
            prior_answer=None,
        )

        self.assertIn("Derived planning grounding summary:", prompt)
        self.assertIn("CPTR 425", prompt)
        self.assertIn("\"remaining_core_courses\"", prompt)
        self.assertIn("\"Programming Languages\"", prompt)
        self.assertIn("\"statistics_options\"", prompt)

    def test_build_deterministic_planning_answer_handles_broad_audit_wording(self):
        service = object.__new__(QueryService)
        planning_context = enrich_planning_context(
            build_planning_context(_sample_student_payload()),
            [_sample_program_profile_chunk()],
        )

        answer = service._build_deterministic_planning_answer(
            question="what courses are left in my program requirements that I have not taken yet or are not in progress",
            planning_context=planning_context,
            retrieved_chunks=[_sample_program_profile_chunk()],
        )

        self.assertIsNotNone(answer)
        self.assertIn("unmet core courses totaling 21 credits", answer)
        self.assertIn("CPTR 440", answer)
        self.assertIn("[planning_context]", answer)

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
            planning_grounding_summary=None,
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
                    "num_predict": 768,
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
                    "num_predict": 768,
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

    def test_generate_answer_retries_after_blank_answered_payload(self):
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
                    "num_predict": 768,
                    "num_ctx": 4096,
                },
            }
        )
        service.llm.generate_json.side_effect = [
            {"status": "answered", "answer": "", "refusal_reason": None},
            {"status": "answered", "answer": "Answer [23-24:000001].", "refusal_reason": None},
        ]

        result = service._generate_answer(
            question="What do I have left?",
            retrieved_chunks=[{"chunkId": "23-24:000001", "bulletin": "23-24", "chunk": "Program Profile"}],
            student=None,
            planning_context=None,
        )

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"], "Answer [23-24:000001].")
        self.assertEqual(service.llm.generate_json.call_count, 2)

    def test_generate_answer_retries_after_grounded_planning_refusal(self):
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
                    "num_predict": 768,
                    "num_ctx": 4096,
                },
            }
        )
        service.llm.generate_json.side_effect = [
            {"status": "refused", "answer": "", "refusal_reason": "Insufficient information provided"},
            {"status": "answered", "answer": "You still have remaining core courses [planning_context].", "refusal_reason": None},
        ]

        result = service._generate_answer(
            question="What do I have left?",
            retrieved_chunks=[{"chunkId": "23-24:000001", "bulletin": "23-24", "chunk": "Program Profile"}],
            student=None,
            planning_context={
                "program": "Computer Science",
                "bulletin_year": "2023-2024",
                "remaining_core_course_codes": ["CPTR 425"],
            },
            planning_grounding_summary="You still have 1 unmet core course: CPTR 425 [planning_context].",
        )

        self.assertEqual(result["status"], "answered")
        self.assertEqual(service.llm.generate_json.call_count, 2)

    def test_generate_answer_rejects_bracket_only_answered_payload(self):
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
                    "num_predict": 768,
                    "num_ctx": 4096,
                },
            }
        )
        service.llm.generate_json.side_effect = [
            {"status": "answered", "answer": "[]", "refusal_reason": None},
            {"status": "answered", "answer": "[]", "refusal_reason": None},
        ]

        result = service._generate_answer(
            question="What should I take next semester?",
            retrieved_chunks=[{"chunkId": "23-24:000001", "bulletin": "23-24", "chunk": "Program Profile"}],
            student=None,
            planning_context=None,
        )

        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["refusal_reason"], "I can only answer from the retrieved bulletin evidence, and the current evidence is not sufficient to answer this safely.")

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
                    "num_predict": 768,
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

    def test_select_model_for_question_prefers_planning_model_for_audit_questions(self):
        service = object.__new__(QueryService)
        service.llm = Mock()
        service.llm.model = "qwen2.5:7b"
        service.llm.planning_model = "qwen2.5:14b"

        selected = service._select_model_for_question(
            normalized_question="what do i have left?",
            grounded_planning_question=True,
        )

        self.assertEqual(selected, "qwen2.5:14b")

    def test_select_model_for_question_uses_default_when_no_planning_override(self):
        service = object.__new__(QueryService)
        service.llm = Mock()
        service.llm.model = "qwen2.5:7b"
        service.llm.planning_model = None

        selected = service._select_model_for_question(
            normalized_question="what does infs 428 cover?",
            grounded_planning_question=False,
        )

        self.assertEqual(selected, "qwen2.5:7b")

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
