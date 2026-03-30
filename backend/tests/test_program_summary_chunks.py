import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.bulletin_ingest.program_summary_chunks import build_program_summary_rows


class ProgramSummaryChunkTests(unittest.TestCase):
    def test_build_program_summary_rows_creates_program_level_summary_with_provenance(self):
        pages = [
            {
                "pageNumber": 1,
                "text": (
                    "Table of Contents\n"
                    "Computer Science BS ................................................. 10\n"
                    "Nursing BSN (Pre-licensure) ...................................... 12\n"
                ),
            },
            {
                "pageNumber": 10,
                "text": (
                    "Computer Science BS\n"
                    "Computer Science prepares students to design and implement software.\n"
                    "Total Credits - 120\n"
                    "Major - 57\n"
                    "CPTR 151 - Computer Science I Credits: 3\n"
                    "CPTR 152 - Computer Science II Credits: 3\n"
                    "Cognates - 28+\n"
                    "MATH 191 - Calculus I Credits: 4\n"
                    "General Education (Andrews Core Experience)\n"
                    "Students must fulfill all Bachelor's Degree requirements listed in the Andrews Core Experience.\n"
                ),
            },
            {
                "pageNumber": 11,
                "text": (
                    "Additional Requirements\n"
                    "No grade lower than C- may be counted toward major or cognate requirements.\n"
                    "Student Learning Outcomes\n"
                    "Graduates of this program will possess the ability to ...\n"
                ),
            },
            {
                "pageNumber": 12,
                "text": (
                    "Nursing BSN (Pre-licensure)\n"
                    "The Bachelor of Science in Nursing program prepares students for licensure.\n"
                    "Total Credits - 126\n"
                    "Major - 65\n"
                    "NRSG 216 - Fundamentals of Nursing Theory and Practice Credits: 5\n"
                    "Cognates - 31\n"
                    "BIOL 221 - Anatomy and Physiology I Credits: 4\n"
                ),
            },
        ]
        raw_rows = [
            {
                "chunkId": "23-24:000101",
                "sourceType": "pdf",
                "pageOccurrence": [10],
            },
            {
                "chunkId": "23-24:000102",
                "sourceType": "pdf",
                "pageOccurrence": [10, 11],
            },
            {
                "chunkId": "23-24:000103",
                "sourceType": "pdf",
                "pageOccurrence": [12],
            },
        ]

        rows = build_program_summary_rows(
            pages=pages,
            raw_rows=raw_rows,
            bulletin_label="23-24",
        )

        self.assertEqual([row["program"] for row in rows], ["Computer Science BS", "Nursing BSN (Pre-licensure)"])

        cs_row = rows[0]
        self.assertEqual(cs_row["sourceType"], "program_summary")
        self.assertEqual(cs_row["pageOccurrence"], [10, 11])
        self.assertEqual(cs_row["sourceChunkIds"], ["23-24:000101", "23-24:000102"])
        self.assertIn("Program Summary: Computer Science BS", cs_row["chunk"])
        self.assertIn("Source Pages: 10, 11", cs_row["chunk"])
        self.assertIn("Source Raw Chunks: 23-24:000101, 23-24:000102", cs_row["chunk"])
        self.assertIn("Total Credits - 120", cs_row["chunk"])
        self.assertIn("Cognates - 28+", cs_row["chunk"])
        self.assertIn("General Education (Andrews Core Experience)", cs_row["chunk"])


if __name__ == "__main__":
    unittest.main()
