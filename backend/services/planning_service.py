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
AUDIT_KEYWORDS = (
    "what do i have left",
    "what do i still need",
    "what courses do i still need",
    "what do i need left",
    "remaining requirements",
    "remaining courses",
    "requirements left",
    "left for my major",
    "still need for my",
)
COMPLETED_STATUSES = {"completed", "transfer", "waived"}
IN_PROGRESS_STATUSES = {"in_progress"}
PLANNED_STATUSES = {"planned"}


def is_planning_question(question: str) -> bool:
    normalized = question.lower().strip()
    return any(keyword in normalized for keyword in PLANNING_KEYWORDS)


def is_audit_question(question: str) -> bool:
    normalized = question.lower().strip()
    return any(keyword in normalized for keyword in AUDIT_KEYWORDS)


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
            "Deterministic audit is currently limited to structured program-profile requirements and saved course history; full university degree-audit rules are not yet configured.",
        ],
    }


def build_deterministic_audit(
    *,
    planning_context: dict | None,
    retrieved_chunks: list[dict],
) -> dict | None:
    if not planning_context or not retrieved_chunks:
        return None

    chunk = next(
        (
            row
            for row in retrieved_chunks
            if isinstance(row.get("structuredData"), dict)
            and isinstance(row["structuredData"].get("program"), dict)
        ),
        None,
    )
    if not chunk:
        return None

    program_payload = chunk["structuredData"]["program"]
    sections = program_payload.get("sections")
    if not isinstance(sections, list) or not sections:
        return None

    completed_rows = planning_context.get("completed_courses", [])
    in_progress_rows = planning_context.get("in_progress_courses", [])
    planned_rows = planning_context.get("planned_courses", [])
    completed_codes = set(planning_context.get("completed_course_codes", []))
    in_progress_codes = set(planning_context.get("in_progress_course_codes", []))
    planned_codes = set(planning_context.get("planned_course_codes", []))
    active_codes = completed_codes | in_progress_codes | planned_codes

    remaining_sections: list[dict] = []
    for section in sections:
        computed = _compute_remaining_section(section, active_codes)
        if computed:
            remaining_sections.append(computed)

    if not remaining_sections:
        return None

    return {
        "program": program_payload.get("program") or chunk.get("program") or planning_context.get("program"),
        "bulletin_year": planning_context.get("bulletin_year"),
        "citation_chunk_id": chunk["chunkId"],
        "completed_courses": completed_rows,
        "in_progress_courses": in_progress_rows,
        "planned_courses": planned_rows,
        "remaining_sections": remaining_sections,
        "other_requirements": _normalize_other_requirements(program_payload.get("other_requirements")),
    }


def render_deterministic_audit_answer(audit: dict) -> str:
    citation = audit["citation_chunk_id"]
    sentences: list[str] = []

    completed_courses = audit.get("completed_courses", [])
    in_progress_courses = audit.get("in_progress_courses", [])
    planned_courses = audit.get("planned_courses", [])
    if completed_courses:
        sentences.append(
            "You have completed "
            + _join_course_codes(completed_courses)
            + " [planning_context]."
        )
    if in_progress_courses:
        sentences.append(
            "You are currently taking "
            + _join_course_codes(in_progress_courses)
            + " [planning_context]."
        )
    if planned_courses:
        sentences.append(
            "You already have these courses planned: "
            + _join_course_codes(planned_courses)
            + " [planning_context]."
        )

    for section in audit.get("remaining_sections", []):
        sentence = _render_remaining_section(section)
        if sentence:
            sentences.append(f"{sentence} [{citation}].")

    for requirement in _important_other_requirements(audit.get("other_requirements", [])):
        cleaned_requirement = requirement.rstrip(". ")
        if cleaned_requirement:
            sentences.append(f"{cleaned_requirement} [{citation}].")

    return " ".join(sentences)


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


def _compute_remaining_section(section: dict, active_codes: set[str]) -> dict | None:
    section_type = (section.get("type") or "").strip().lower()
    title = (section.get("section") or "").strip()
    if not title:
        return None

    if section_type == "required_courses":
        courses = _normalize_course_rows(section.get("courses"))
        remaining_courses = [row for row in courses if row["code"] and row["code"] not in active_codes]
        if remaining_courses:
            return {
                "kind": "required_courses",
                "title": title,
                "remaining_courses": remaining_courses,
            }
        return None

    if section_type == "choose_from_pool":
        options = _normalize_course_rows(section.get("options"))
        if not options:
            rules = _normalize_rules(section.get("rules"))
            if rules:
                return {
                    "kind": "rule_only",
                    "title": title,
                    "rules": rules,
                }
            return None

        matched_options = [row for row in options if row["code"] in active_codes]
        matched_credits = sum(int(row.get("credits") or 0) for row in matched_options)
        required_credits = _parse_required_credits(section.get("required_credits"))
        remaining_options = [row for row in options if row["code"] not in active_codes]

        if required_credits is not None:
            remaining_credits = max(required_credits - matched_credits, 0)
            if remaining_credits <= 0:
                return None
            return {
                "kind": "choose_from_pool",
                "title": title,
                "remaining_credits": remaining_credits,
                "remaining_options": remaining_options or options,
            }

        if matched_options:
            return None
        return {
            "kind": "choose_one",
            "title": title,
            "remaining_options": remaining_options or options,
        }

    return None


def _normalize_course_rows(rows) -> list[dict]:
    if not isinstance(rows, list):
        return []
    normalized: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = (
            row.get("course")
            or row.get("code")
            or row.get("course_code")
        )
        title = (
            row.get("title")
            or row.get("course_title")
            or code
        )
        if not code or code in seen:
            continue
        normalized.append(
            {
                "code": str(code).strip(),
                "title": str(title or code).strip(),
                "credits": _parse_required_credits(row.get("credits")) or 0,
            }
        )
        seen.add(str(code).strip())
    return normalized


def _normalize_rules(rules) -> list[str]:
    if not isinstance(rules, list):
        return []
    cleaned = [str(rule).strip() for rule in rules if str(rule).strip()]
    return _merge_wrapped_fragments(cleaned)


def _parse_required_credits(value) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    return int(match.group(0))


def _join_course_codes(rows: list[dict]) -> str:
    codes = [row["code"] for row in rows if row.get("code")]
    if not codes:
        return ""
    if len(codes) == 1:
        return codes[0]
    if len(codes) == 2:
        return f"{codes[0]} and {codes[1]}"
    return ", ".join(codes[:-1]) + f", and {codes[-1]}"


def _render_remaining_section(section: dict) -> str:
    title = section["title"]
    lowered = title.lower()

    if section["kind"] == "required_courses":
        codes = _join_course_codes(section["remaining_courses"])
        if "core courses" in lowered:
            return f"You still need these core courses: {codes}"
        if "cognates - required" in lowered:
            return f"You still need these required cognate courses: {codes}"
        return f"You still need these courses from {title}: {codes}"

    if section["kind"] == "choose_from_pool":
        options = _join_course_codes(section["remaining_options"])
        remaining_credits = section["remaining_credits"]
        if "choose three" in lowered and remaining_credits == 9:
            return f"You still need three courses from {title}: {options}"
        if "electives" in lowered:
            return f"You still need {remaining_credits} elective credits from these options: {options}"
        if "statistics" in lowered:
            return f"You still need {remaining_credits} credits from the statistics cognate options: {options}"
        if "science" in lowered:
            return f"You still need {remaining_credits} credits from the science cognate options: {options}"
        return f"You still need {remaining_credits} credits from {title}: {options}"

    if section["kind"] == "choose_one":
        options = _join_course_codes(section["remaining_options"])
        if "statistics" in lowered:
            return f"You still need one statistics cognate from: {options}"
        if "science" in lowered:
            return f"You still need one science cognate from: {options}"
        return f"You still need one course from {title}: {options}"

    if section["kind"] == "rule_only":
        if "electives" in lowered:
            return _render_elective_rule_summary(section["rules"])
        rules = "; ".join(section["rules"])
        return f"You still need to satisfy {title}: {rules}"

    return ""


def _normalize_other_requirements(rows) -> list[str]:
    if not isinstance(rows, list):
        return []
    cleaned = [str(row).strip() for row in rows if str(row).strip()]
    return _merge_wrapped_fragments(cleaned)


def _important_other_requirements(requirements: list[str]) -> list[str]:
    return [
        row for row in requirements
        if "andrews core" in row.lower() or "no grade lower than c-" in row.lower()
    ]


def _render_elective_rule_summary(rules: list[str]) -> str:
    if not rules:
        return "You still need to complete the elective requirement"

    primary_rule = rules[0].rstrip(". ")
    substitution_courses = _extract_substitution_courses(rules[1:])
    if not substitution_courses:
        return f"You still need to complete the elective requirement: {primary_rule}"

    return (
        f"You still need to complete the elective requirement: {primary_rule}. "
        "Up to 6 of those elective credits may instead come from "
        f"{_join_values(substitution_courses)}"
    ).replace(". Up to 6", "; Up to 6")


def _merge_wrapped_fragments(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if not merged:
            merged.append(line)
            continue

        previous = merged[-1]
        if _should_merge_wrapped_line(previous, line):
            merged[-1] = f"{previous.rstrip()} {line.lstrip()}".strip()
        else:
            merged.append(line)
    return merged


def _should_merge_wrapped_line(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    if previous.endswith((".", "!", "?")):
        return False
    if current[0].islower() or current[0].isdigit():
        return True
    if previous.endswith(("Core", "INFS", "elective", "major", "and")):
        return True
    return False


def _extract_substitution_courses(rules: list[str]) -> list[str]:
    courses: list[str] = []
    for rule in rules:
        courses.extend(_expand_course_list_fragment(rule))

    deduped: list[str] = []
    seen: set[str] = set()
    for course in courses:
        if course in seen:
            continue
        deduped.append(course)
        seen.add(course)
    return deduped


def _expand_course_list_fragment(text: str) -> list[str]:
    fragment = text.strip().rstrip(".")
    if not fragment:
        return []

    if "substituted for" in fragment.lower():
        return []

    match = re.match(r"^([A-Z]{2,4})\s+(.+)$", fragment)
    if match:
        subject = match.group(1)
        tail = match.group(2).replace(" and ", ", ")
        numbers = re.findall(r"\b(\d{3}[A-Z]?)\b", tail)
        if numbers:
            return [f"{subject} {number}" for number in numbers]

    explicit = re.findall(r"\b([A-Z]{2,4})\s+(\d{3}[A-Z]?)\b", fragment)
    return [f"{subject} {number}" for subject, number in explicit]


def _join_values(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"
