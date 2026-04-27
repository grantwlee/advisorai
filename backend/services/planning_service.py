import re


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
    completed_rows = [
        _serialize_course(row)
        for row in enrollments
        if row.get("status") in COMPLETED_STATUSES and row.get("course", {}).get("code")
    ]
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
        "completed_courses": completed_rows,
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


def enrich_planning_context(
    planning_context: dict | None,
    retrieved_chunks: list[dict],
) -> dict | None:
    if not planning_context:
        return None

    profile = _select_program_profile_chunk(
        retrieved_chunks,
        planning_context.get("program"),
    )
    if not profile:
        return planning_context

    structured = profile.get("structuredData")
    if not isinstance(structured, dict):
        return planning_context
    program_payload = structured.get("program")
    if not isinstance(program_payload, dict):
        return planning_context

    sections = program_payload.get("sections")
    if not isinstance(sections, list):
        return planning_context

    tracked_codes = {
        *planning_context.get("completed_course_codes", []),
        *planning_context.get("in_progress_course_codes", []),
        *planning_context.get("planned_course_codes", []),
    }

    core_courses = _section_course_rows(_find_section(sections, "Core Courses"), "courses")
    remaining_core_courses = [
        row for row in core_courses if row["code"] and row["code"] not in tracked_codes
    ]

    choose_three = _find_section(sections, "Choose Three Courses")
    choose_three_options = _section_course_rows(choose_three, "options")
    choose_three_completed_count = sum(
        1 for row in choose_three_options if row["code"] in tracked_codes
    )
    choose_three_remaining_count = max(0, 3 - choose_three_completed_count)
    choose_three_remaining_options = [
        row for row in choose_three_options if row["code"] and row["code"] not in tracked_codes
    ]

    elective_section = _find_section(sections, "Electives")
    elective_required_credits = _parse_credit_value(
        (elective_section or {}).get("required_credits")
    )

    required_cognates = _section_course_rows(_find_section(sections, "Cognates - Required"), "courses")
    remaining_required_cognates = [
        row for row in required_cognates if row["code"] and row["code"] not in tracked_codes
    ]

    statistics_section = _find_section_contains(sections, "Statistics")
    statistics_options = _section_course_rows(statistics_section, "options")
    statistics_completed = any(row["code"] in tracked_codes for row in statistics_options)

    science_section = _find_section_contains(sections, "Science")
    science_options = _section_course_rows(science_section, "options")
    science_completed = any(row["code"] in tracked_codes for row in science_options)

    choose_one_section = _find_section(sections, "Choose One Courses")
    choose_one_options = _section_course_rows(choose_one_section, "options")
    choose_one_completed = any(row["code"] in tracked_codes for row in choose_one_options)

    recommended_next_courses = [
        {
            "code": row["code"],
            "title": row["title"],
            "credits": row["credits"],
            "category": "Core",
            "rationale": "Unmet core requirement from the retrieved program profile.",
        }
        for row in remaining_core_courses[:3]
    ]
    if len(recommended_next_courses) < 3:
        for row in choose_three_remaining_options:
            recommended_next_courses.append(
                {
                    "code": row["code"],
                    "title": row["title"],
                    "credits": row["credits"],
                    "category": "Choose Three",
                    "rationale": "Eligible option from the retrieved program profile.",
                }
            )
            if len(recommended_next_courses) >= 3:
                break

    enriched = dict(planning_context)
    enriched.update(
        {
            "scope_note": (
                "Deterministic planning context compares the student's tracked courses against "
                "the retrieved structured program profile. Remaining counts and recommendations "
                "are scoped to explicitly structured program requirements and may not cover every "
                "university-wide audit rule."
            ),
            "derived_from_chunk_ids": [profile["chunkId"]],
            "remaining_requirement_count": len(remaining_core_courses),
            "remaining_credits": sum(row["credits"] for row in remaining_core_courses),
            "remaining_core_course_codes": [row["code"] for row in remaining_core_courses],
            "remaining_core_courses": remaining_core_courses,
            "choose_three_remaining_count": choose_three_remaining_count,
            "choose_three_remaining_options": choose_three_remaining_options,
            "remaining_elective_credits": elective_required_credits,
            "remaining_required_cognate_course_codes": [row["code"] for row in remaining_required_cognates],
            "remaining_required_cognate_courses": remaining_required_cognates,
            "statistics_requirement_remaining": not statistics_completed,
            "statistics_option_codes": [row["code"] for row in statistics_options],
            "statistics_options": statistics_options,
            "science_requirement_remaining": not science_completed,
            "science_option_codes": [row["code"] for row in science_options],
            "science_options": science_options,
            "choose_one_requirement_remaining": not choose_one_completed,
            "choose_one_option_codes": [row["code"] for row in choose_one_options],
            "choose_one_options": choose_one_options,
            "recommended_next_courses": recommended_next_courses,
        }
    )

    context_gaps = list(enriched.get("context_gaps", []))
    deterministic_gap = (
        "Deterministic planning summaries are currently derived from structured program-profile "
        "requirements and tracked course history; prerequisite chains, term sequencing, and full "
        "university degree-audit rules are still limited."
    )
    if deterministic_gap not in context_gaps:
        context_gaps.append(deterministic_gap)
    enriched["context_gaps"] = context_gaps
    return enriched


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


def _select_program_profile_chunk(
    retrieved_chunks: list[dict],
    program: str | None,
) -> dict | None:
    normalized_program = (program or "").lower()
    for chunk in retrieved_chunks:
        structured = chunk.get("structuredData")
        if not isinstance(structured, dict) or structured.get("kind") != "program_profile":
            continue
        structured_program = structured.get("program")
        program_name = ""
        if isinstance(structured_program, dict):
            program_name = str(structured_program.get("program") or "")
        combined = " ".join(
            part for part in (chunk.get("program"), chunk.get("sectionTitle"), program_name) if part
        ).lower()
        if not normalized_program or normalized_program in combined:
            return chunk
    for chunk in retrieved_chunks:
        structured = chunk.get("structuredData")
        if isinstance(structured, dict) and structured.get("kind") == "program_profile":
            return chunk
    return None


def _find_section(sections: list[dict], title: str) -> dict | None:
    for section in sections:
        if str(section.get("section") or "").strip().lower() == title.lower():
            return section
    return None


def _find_section_contains(sections: list[dict], text: str) -> dict | None:
    needle = text.lower()
    for section in sections:
        if needle in str(section.get("section") or "").lower():
            return section
    return None


def _section_course_rows(section: dict | None, key: str) -> list[dict]:
    if not isinstance(section, dict):
        return []
    rows = section.get(key)
    if not isinstance(rows, list):
        return []
    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("course") or row.get("code") or "").strip()
        if not code:
            continue
        normalized.append(
            {
                "code": code,
                "title": str(row.get("title") or code).strip(),
                "credits": _parse_credit_value(row.get("credits")),
            }
        )
    return normalized


def _parse_credit_value(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    text = str(value)
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else 0
