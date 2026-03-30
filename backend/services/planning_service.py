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


def build_planning_context(student: dict | None) -> dict | None:
    if not student:
        return None

    enrollments = student.get("courses", [])
    completed_codes = sorted(
        {
            row["course"]["code"]
            for row in enrollments
            if row.get("status") in COMPLETED_STATUSES and row.get("course", {}).get("code")
        }
    )
    in_progress_rows = [
        _serialize_course(row)
        for row in enrollments
        if row.get("status") in IN_PROGRESS_STATUSES and row.get("course", {}).get("code")
    ]
    planned_rows = [
        _serialize_course(row)
        for row in enrollments
        if row.get("status") in PLANNED_STATUSES and row.get("course", {}).get("code")
    ]

    return {
        "program": student["program"],
        "bulletin_year": student.get("bulletin_year"),
        "completed_course_codes": completed_codes,
        "in_progress_course_codes": [row["code"] for row in in_progress_rows],
        "planned_course_codes": [row["code"] for row in planned_rows],
        "completed_credits": _sum_credits(enrollments, COMPLETED_STATUSES),
        "in_progress_credits": _sum_credits(enrollments, IN_PROGRESS_STATUSES),
        "planned_credits": _sum_credits(enrollments, PLANNED_STATUSES),
        "in_progress_courses": in_progress_rows,
        "planned_courses": planned_rows,
        "context_gaps": [
            "No class meeting-time schedule is stored yet, so this planner cannot check time conflicts.",
            "No structured degree-audit rules are configured, so course recommendations must be inferred from retrieved bulletin evidence and the saved course history.",
        ],
    }


def _serialize_course(row: dict) -> dict:
    course = row.get("course") or {}
    return {
        "code": course.get("code"),
        "title": course.get("title") or course.get("code"),
        "credits": int(course.get("credits") or 0),
    }


def _sum_credits(enrollments: list[dict], statuses: set[str]) -> int:
    return sum(
        int((row.get("course") or {}).get("credits") or 0)
        for row in enrollments
        if row.get("status") in statuses
    )
