import json
import os
from functools import lru_cache

from services.year_utils import expand_bulletin_year, normalize_bulletin_year


RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "degree_audit_rules.json",
)
AUDIT_KEYWORDS = (
    "what do i have left",
    "what courses do i have left",
    "what courses do i still need",
    "remaining courses",
    "remaining requirements",
    "degree audit",
    "still need",
)


@lru_cache(maxsize=1)
def load_degree_audit_rules() -> dict:
    with open(RULES_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def is_degree_audit_question(question: str) -> bool:
    normalized = question.lower().strip()
    return any(keyword in normalized for keyword in AUDIT_KEYWORDS)


def get_program_rules(program: str, bulletin_year: str | None) -> dict | None:
    rules = load_degree_audit_rules()
    normalized_year = expand_bulletin_year(bulletin_year) or bulletin_year
    program_rules = rules.get(program, {})
    if normalized_year and normalized_year in program_rules:
        return program_rules[normalized_year]

    short_year = normalize_bulletin_year(bulletin_year)
    expanded = expand_bulletin_year(short_year)
    if expanded and expanded in program_rules:
        return program_rules[expanded]
    return None


def summarize_degree_audit(student: dict) -> dict | None:
    rules = get_program_rules(student["program"], student.get("bulletin_year"))
    if not rules:
        return None

    completed_statuses = {"completed", "transfer", "waived"}
    in_progress_statuses = {"in_progress", "planned"}
    enrollments = student.get("courses", [])
    completed_codes = {
        row["course"]["code"]
        for row in enrollments
        if row.get("status") in completed_statuses and row.get("course", {}).get("code")
    }
    in_progress_codes = {
        row["course"]["code"]
        for row in enrollments
        if row.get("status") in in_progress_statuses and row.get("course", {}).get("code")
    }

    completed = []
    in_progress = []
    remaining = []

    for requirement in rules.get("requirements", []):
        code = requirement["code"]
        if code in completed_codes:
            completed.append(requirement)
        elif code in in_progress_codes:
            in_progress.append(requirement)
        else:
            remaining.append(requirement)

    return {
        "program": student["program"],
        "bulletin_year": student.get("bulletin_year"),
        "scope_note": rules.get("scope_note"),
        "summary_query": rules.get("summary_query"),
        "completed": completed,
        "in_progress": in_progress,
        "remaining": remaining,
        "total_required": len(rules.get("requirements", [])),
    }
