import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.bulletin_ingest.program_summary_chunks import (
    build_program_summary_rows,
    build_structured_program_catalog,
)


class ProgramSummaryChunkTests(unittest.TestCase):
    def test_build_program_summary_rows_creates_one_program_profile_chunk_per_program(self):
        pages = [
            {
                "pageNumber": 1,
                "text": (
                    "Table of Contents\n"
                    "Computer Science BS ................................................. 10\n"
                    "Data Analytics Minor ............................................... 12\n"
                ),
            },
            {
                "pageNumber": 10,
                "text": (
                    "Computer Science BS\n"
                    "Computer Science prepares students to design and implement software.\n"
                    "Total Credits - 120\n"
                    "Core - 42\n"
                    "CPTR 151 - Computer Science I Credits: 3\n"
                    "CPTR 152 - Computer Science II Credits: 3\n"
                    "Choose three of the following courses: Credits / Units: 9\n"
                    "CPTR 251 - Server Application Development Credits: 3\n"
                    "CPTR 252 - Mobile Application Development Credits: 3\n"
                    "Electives - 15\n"
                    "Choose 15 credits in consultation with academic advisor from CPTR courses.\n"
                    "Cognates - 28+\n"
                    "MATH 191 - Calculus I Credits: 4\n"
                    "Statistics\n"
                    "Choose one of the following courses:\n"
                    "STAT 285 - Introduction to Applied Statistics Credits: 3\n"
                    "STAT 340 - Probability Theory with Statistical Applications Credits: 3\n"
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
                    "Data Analytics Minor\n"
                    "This minor introduces students to data analysis.\n"
                    "Core - 18\n"
                    "CPTR 230 - Data Science Fundamentals Credits: 3\n"
                    "INFS 428 - Database Systems Design and Development Credits: 3\n"
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

        self.assertEqual(len(rows), 2)

        cs_row = next(row for row in rows if row["program"] == "Computer Science BS")
        self.assertEqual(cs_row["sourceType"], "program_summary")
        self.assertEqual(cs_row["sectionType"], "program_profile")
        self.assertEqual(cs_row["pageOccurrence"], [10, 11])
        self.assertEqual(cs_row["programPageOccurrence"], [10, 11])
        self.assertEqual(cs_row["sourceChunkIds"], ["23-24:000101", "23-24:000102"])
        self.assertIn("Program Profile: Computer Science BS", cs_row["chunk"])
        self.assertIn("Program Type: major", cs_row["chunk"])

        structured = cs_row["structuredData"]
        self.assertEqual(structured["kind"], "program_profile")
        self.assertEqual(structured["program"]["program_type"], "major")
        self.assertEqual(structured["program"]["award"], "BS")
        self.assertEqual(structured["program"]["pdf_pages"], [10, 11])
        self.assertEqual(structured["program"]["summary"]["core_credits"], "42")
        self.assertTrue(
            any(section["section"] == "Core Courses" for section in structured["program"]["sections"])
        )
        self.assertTrue(
            any(section["section"] == "Choose Three Courses" for section in structured["program"]["sections"])
        )

        minor_row = next(row for row in rows if row["program"] == "Data Analytics Minor")
        self.assertEqual(minor_row["structuredData"]["program"]["program_type"], "minor")
        self.assertIsNone(minor_row["structuredData"]["program"]["award"])

        catalog = build_structured_program_catalog(
            summary_rows=rows,
            bulletin_label="23-24",
            source_pdf="Bulletin_23-24_PDF_FINAL.pdf",
        )
        self.assertEqual(len(catalog["programs"]), 2)
        catalog_cs = next(program for program in catalog["programs"] if program["program"] == "Computer Science BS")
        self.assertEqual(catalog_cs["pdf_pages"], [10, 11])


if __name__ == "__main__":
    unittest.main()
