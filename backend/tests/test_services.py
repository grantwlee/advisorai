import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.degree_audit import summarize_degree_audit
from services.planning_service import build_planning_context, is_planning_question
from services.query_service import QueryService
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


class DegreeAuditTests(unittest.TestCase):
    def test_summarize_degree_audit_uses_completed_and_in_progress_courses(self):
        student = {
            "student_id": "S1001",
            "name": "Alex Johnson",
            "program": "Computer Science",
            "bulletin_year": "2023-2024",
            "courses": [
                {"status": "completed", "course": {"code": "CPTR 151"}},
                {"status": "completed", "course": {"code": "CPTR 152"}},
                {"status": "in_progress", "course": {"code": "CPTR 276"}},
            ],
        }
        summary = summarize_degree_audit(student)
        self.assertIsNotNone(summary)
        self.assertTrue(any(row["code"] == "CPTR 151" for row in summary["completed"]))
        self.assertTrue(any(row["code"] == "CPTR 276" for row in summary["in_progress"]))
        self.assertTrue(any(row["code"] == "CPTR 230" for row in summary["remaining"]))


class PlanningServiceTests(unittest.TestCase):
    def test_is_planning_question_detects_next_semester_language(self):
        self.assertTrue(is_planning_question("What should I take next semester?"))

    def test_build_planning_context_recommends_eligible_courses(self):
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
        self.assertEqual(
            [row["code"] for row in context["recommended_next_courses"]],
            ["CPTR 425", "CPTR 430", "CPTR 437"],
        )
        self.assertIn(
            "No class meeting-time schedule is stored yet, so this planner cannot check time conflicts.",
            context["context_gaps"],
        )


class QueryServiceTests(unittest.TestCase):
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
        )

        self.assertIn("[23-24:007600]", repaired)
        verified = verify_answer(repaired, retrieved)
        self.assertTrue(verified["passed"])

    def test_planning_fallback_answer_returns_cited_sentence(self):
        service = object.__new__(QueryService)
        planning_context = {
            "program": "Computer Science",
            "recommended_next_courses": [
                {"code": "CPTR 425"},
                {"code": "CPTR 430"},
                {"code": "CPTR 437"},
            ],
        }
        retrieved = [
            {
                "chunkId": "23-24:007646",
                "bulletin": "23-24",
                "chunk": (
                    "Computer Science BS CPTR 425 Programming Languages "
                    "CPTR 430 Analysis of Algorithms CPTR 437 Formal Theory of Computation"
                ),
                "score": 3.0,
            }
        ]

        answer = service._build_planning_fallback_answer(planning_context, retrieved)

        self.assertIsNotNone(answer)
        self.assertIn("[23-24:007646]", answer)
        self.assertTrue(verify_answer(answer, retrieved)["passed"])


if __name__ == "__main__":
    unittest.main()
