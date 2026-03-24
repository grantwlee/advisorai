from database import session
from models import Course
from services.degree_audit import get_program_rules, summarize_degree_audit


PLANNING_KEYWORDS = (
    "next semester",
    "next term",
    "what should i take",
    "what classes should i take",
    "what courses should i take",
    "course plan",
    "plan my schedule",
    "build my schedule",
    "semester plan",
    "recommend courses",
    "recommended courses",
    "avoid conflicts",
    "schedule conflict",
)
COMPLETED_STATUSES = {"completed", "transfer", "waived"}
IN_PROGRESS_STATUSES = {"in_progress"}
PLANNED_STATUSES = {"planned"}


def is_planning_question(question: str) -> bool:
    normalized = question.lower().strip()
    return any(keyword in normalized for keyword in PLANNING_KEYWORDS)


def build_planning_context(
    student: dict | None,
    *,
    audit_summary: dict | None = None,
    max_recommendations: int = 3,
    credit_cap: int = 12,
) -> dict | None:
    if not student:
        return None

    rules = get_program_rules(student["program"], student.get("bulletin_year"))
    if not rules:
        return None

    audit_summary = audit_summary or summarize_degree_audit(student)
    if not audit_summary:
        return None

    enrollments = student.get("courses", [])
    completed_codes = {
        row["course"]["code"]
        for row in enrollments
        if row.get("status") in COMPLETED_STATUSES and row.get("course", {}).get("code")
    }
    in_progress_codes = {
        row["course"]["code"]
        for row in enrollments
        if row.get("status") in IN_PROGRESS_STATUSES and row.get("course", {}).get("code")
    }
    planned_codes = {
        row["course"]["code"]
        for row in enrollments
        if row.get("status") in PLANNED_STATUSES and row.get("course", {}).get("code")
    }

    catalog = _load_course_catalog({requirement["code"] for requirement in rules["requirements"]})
    completed_credits = _sum_credits(enrollments, COMPLETED_STATUSES)
    in_progress_credits = _sum_credits(enrollments, IN_PROGRESS_STATUSES)
    planned_credits = _sum_credits(enrollments, PLANNED_STATUSES)

    satisfied_for_next_term = completed_codes | in_progress_codes
    outstanding: list[dict] = []
    eligible: list[dict] = []
    blocked: list[dict] = []
    planned_requirements: list[dict] = []

    for requirement in rules["requirements"]:
        hydrated = _hydrate_requirement(requirement, catalog)
        code = hydrated["code"]
        if code in completed_codes:
            continue
        if code in in_progress_codes:
            continue
        if code in planned_codes:
            planned_requirements.append(hydrated)
            continue

        missing = [
            prerequisite
            for prerequisite in hydrated["prerequisites"]
            if prerequisite not in satisfied_for_next_term
        ]
        hydrated["missing_prerequisites"] = missing
        outstanding.append(hydrated)
        if missing:
            blocked.append(hydrated)
        else:
            hydrated["rationale"] = (
                "Eligible for next-term planning based on tracked progress and configured prerequisites."
            )
            eligible.append(hydrated)

    recommended: list[dict] = []
    running_credits = 0
    for requirement in eligible:
        credits = int(requirement.get("credits") or 0)
        if recommended and running_credits + credits > credit_cap:
            break
        recommended.append(requirement)
        running_credits += credits
        if len(recommended) >= max_recommendations:
            break

    return {
        "program": student["program"],
        "bulletin_year": student.get("bulletin_year"),
        "scope_note": (
            f"{rules.get('scope_note', '')} Planning recommendations are generated from the saved "
            "student profile and configured rules, then grounded with retrieved bulletin evidence."
        ).strip(),
        "summary_query": rules.get("summary_query"),
        "completed_course_codes": sorted(completed_codes),
        "in_progress_course_codes": sorted(in_progress_codes),
        "planned_course_codes": sorted(planned_codes),
        "completed_credits": completed_credits,
        "in_progress_credits": in_progress_credits,
        "planned_credits": planned_credits,
        "remaining_requirement_count": len(outstanding),
        "remaining_credits": sum(int(row.get("credits") or 0) for row in outstanding),
        "recommended_next_courses": recommended,
        "planned_courses": planned_requirements,
        "blocked_courses": blocked[:5],
        "context_gaps": [
            "No class meeting-time schedule is stored yet, so this planner cannot check time conflicts.",
            "Recommendations are scoped to the configured demo program rules and tracked course history.",
        ],
    }


def _load_course_catalog(course_codes: set[str]) -> dict[str, dict]:
    if not course_codes:
        return {}

    try:
        rows = session.query(Course).filter(Course.code.in_(sorted(course_codes))).all()
    except Exception:
        return {}
    return {
        row.code: {
            "code": row.code,
            "title": row.title,
            "credits": row.credits,
        }
        for row in rows
    }


def _hydrate_requirement(requirement: dict, catalog: dict[str, dict]) -> dict:
    course = catalog.get(requirement["code"], {})
    return {
        "code": requirement["code"],
        "title": course.get("title") or requirement.get("title") or requirement["code"],
        "credits": int(course.get("credits") or requirement.get("credits") or 3),
        "category": requirement.get("category"),
        "citation_query": requirement.get("citation_query") or requirement["code"],
        "prerequisites": list(requirement.get("prerequisites") or []),
    }


def _sum_credits(enrollments: list[dict], statuses: set[str]) -> int:
    return sum(
        int((row.get("course") or {}).get("credits") or 0)
        for row in enrollments
        if row.get("status") in statuses
    )
