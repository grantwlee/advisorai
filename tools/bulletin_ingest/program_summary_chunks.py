from __future__ import annotations

import json
import re
from typing import Any


TOC_PAGE_LIMIT = 20
TOC_ENTRY_PATTERN = re.compile(r"^(?P<title>.+?)\.{3,}\s*(?P<page>\d{1,4})$")
UNDERGRAD_DEGREE_PATTERN = re.compile(
    r"\b(AS|AT|BA|BA/BS|BS/BA|BBA|BBA/BA|BS|BSN|BSMLS|BSPH|BT|BHS|BID|BSA)\b",
    re.IGNORECASE,
)
AWARD_PATTERN = re.compile(
    r"\b(AS|AT|BA/BS|BS/BA|BBA/BA|BBA|BSN|BSMLS|BSPH|BHS|BID|BSA|BA|BS|BT)\b",
    re.IGNORECASE,
)
EXCLUDED_TITLE_KEYWORDS = (
    "graduate",
    "master",
    "doctor",
    "phd",
    "edd",
    "dpt",
    "dnp",
    "mba",
    "ms",
    "ma ",
    " mdiv",
    "concentration mph",
)
RELEVANT_SECTION_PREFIXES = (
    "Total Credits -",
    "Major -",
    "Core -",
    "Business Core -",
    "Flight -",
    "Business -",
    "Electives",
    "Math Electives",
    "Cognates -",
    "Application Area -",
    "Applied Area Minor -",
    "Aviation Maintenance -",
    "General Education (Andrews Core Experience)",
    "Additional Requirements",
    "Graduation Requirements",
    "Admission Requirements",
    "Maintaining Academic Standing",
    "Practicum",
    "Program Accreditation",
    "Residence Requirement",
    "Transfer Credits",
)
BREAK_SECTION_PREFIXES = (
    "Student Learning Outcomes",
    "Undergraduate Minors",
    "Masters",
    "Post-Masters",
    "Additional Information",
)
IGNORED_TOC_LINES = (
    "table of contents",
    "contents",
)
RULE_SECTION_TITLES = {
    "Additional Requirements",
    "Admission Requirements",
    "General Education (Andrews Core Experience)",
    "Graduation Requirements",
    "Maintaining Academic Standing",
    "Practicum",
    "Program Accreditation",
    "Residence Requirement",
    "Transfer Credits",
}
GROUPED_SECTION_TITLES = {"Cognates"}
SUBGROUP_CHOICE_TITLES = {
    "statistics": "Statistics",
    "science": "Science",
    "sciences": "Science",
    "ethics": "Ethics",
    "visualization/modeling": "Visualization/Modeling",
    "data management": "Data Management",
}
COURSE_ENTRY_PATTERN = re.compile(
    r"(?P<course>[A-Z]{2,5}\s*\d{3}[A-Z]?(?:/[A-Z]{2,5}\s*\d{3}[A-Z]?)?)\s*-\s*"
    r"(?P<title>.+?)\s+Credits:\s*(?P<credits>.+?)(?=(?:\s+[A-Z]{2,5}\s*\d{3}[A-Z]?\s*-)|$)"
)


def build_program_summary_rows(
    *,
    pages: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    bulletin_label: str,
) -> list[dict[str, Any]]:
    entries = parse_program_entries(pages)
    if not entries:
        return []

    summary_rows: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries):
        next_entry = entries[idx + 1] if idx + 1 < len(entries) else None
        page_slices = extract_program_source_pages(pages, entry, next_entry)
        if not page_slices:
            continue

        program_pages = [page["pageNumber"] for page in page_slices]
        program_source_chunk_ids = _source_chunk_ids_for_pages(raw_rows, program_pages)
        if not program_source_chunk_ids:
            continue

        line_rows = extract_program_line_rows(page_slices)
        if not line_rows:
            continue

        structure = extract_program_structure(line_rows)
        profile = build_program_profile(entry, structure, program_pages)
        chunk_text = format_program_profile_chunk(
            program_profile=profile,
            bulletin_label=bulletin_label,
            source_chunk_ids=program_source_chunk_ids,
        )
        if not chunk_text:
            continue

        summary_rows.append(
            {
                "chunk": chunk_text,
                "pageOccurrence": program_pages,
                "charCount": len(chunk_text),
                "sourceType": "program_summary",
                "program": entry["title"],
                "sectionTitle": entry["title"],
                "sectionType": "program_profile",
                "sourcePageOccurrence": program_pages,
                "sourceChunkIds": program_source_chunk_ids,
                "programPageOccurrence": program_pages,
                "structuredData": {
                    "kind": "program_profile",
                    "program": profile,
                },
            }
        )

    return summary_rows


def build_structured_program_catalog(
    *,
    summary_rows: list[dict[str, Any]],
    bulletin_label: str,
    source_pdf: str,
) -> dict[str, Any]:
    programs: list[dict[str, Any]] = []
    for row in summary_rows:
        structured = row.get("structuredData") or {}
        if structured.get("kind") != "program_profile":
            continue

        program = dict(structured.get("program") or {})
        if not program:
            continue

        program["bulletin"] = bulletin_label
        program["source_pdf"] = source_pdf
        programs.append(program)

    return {
        "bulletin": bulletin_label,
        "source_pdf": source_pdf,
        "programs": programs,
    }


def parse_program_entries(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buffered = ""
    entries: list[dict[str, Any]] = []
    order = 0

    for page in pages:
        if page["pageNumber"] > TOC_PAGE_LIMIT:
            break

        for raw_line in page["text"].splitlines():
            line = _clean_line(raw_line)
            if not line:
                continue
            if line.lower() in IGNORED_TOC_LINES:
                buffered = ""
                continue

            candidate = f"{buffered} {line}".strip() if buffered else line
            match = TOC_ENTRY_PATTERN.match(candidate)
            if match:
                title = normalize_entry_title(match.group("title"))
                start_page = int(match.group("page"))
                classification = classify_program_title(title)
                if classification:
                    entries.append(
                        {
                            "title": title,
                            "page": start_page,
                            "order": order,
                            "program_type": classification["program_type"],
                            "award": classification.get("award"),
                        }
                    )
                    order += 1
                buffered = ""
                continue

            if re.search(r"\.{3,}\s*\d{1,4}$", line):
                buffered = ""
            elif len(line) >= 8:
                buffered = candidate[-200:]

    entries.sort(key=lambda item: (item["page"], item["order"]))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for entry in entries:
        key = (entry["title"], entry["page"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def classify_program_title(title: str) -> dict[str, str] | None:
    lowered = title.lower()
    if any(keyword in lowered for keyword in EXCLUDED_TITLE_KEYWORDS):
        return None
    if "undergraduate minors" in lowered or lowered in {"minors", "certificates"}:
        return None

    if re.search(r"\bminor\b", lowered):
        return {"program_type": "minor", "award": None}
    if re.search(r"\bcertificate\b", lowered):
        return {"program_type": "certificate", "award": None}
    if re.search(r"\bconcentration\b", lowered):
        return {
            "program_type": "concentration",
            "award": extract_award(title),
        }
    if UNDERGRAD_DEGREE_PATTERN.search(title):
        return {
            "program_type": "major",
            "award": extract_award(title),
        }
    return None


def extract_award(title: str) -> str | None:
    match = AWARD_PATTERN.search(title)
    if not match:
        return None
    return match.group(1).upper()


def extract_program_source_pages(
    pages: list[dict[str, Any]],
    entry: dict[str, Any],
    next_entry: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    pages_by_number = {page["pageNumber"]: page["text"] for page in pages}
    last_page = pages[-1]["pageNumber"] if pages else entry["page"]
    end_page = next_entry["page"] if next_entry else last_page

    source_pages: list[dict[str, Any]] = []
    for page_number in range(entry["page"], end_page + 1):
        page_text = pages_by_number.get(page_number, "")
        if not page_text.strip():
            continue

        sliced = page_text
        if page_number == entry["page"]:
            start_match = _find_title_match(page_text, entry["title"])
            if start_match:
                sliced = page_text[start_match.end():]

        if next_entry and page_number == next_entry["page"]:
            end_match = _find_title_match(sliced, next_entry["title"])
            if end_match:
                sliced = sliced[: end_match.start()]

        sliced = normalize_program_text(sliced)
        if sliced:
            source_pages.append({"pageNumber": page_number, "text": sliced})

    return source_pages


def extract_program_line_rows(page_slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in page_slices:
        for raw_line in page["text"].splitlines():
            line = _clean_line(raw_line)
            if not line or line == "\u2022":
                continue
            rows.append({"text": line, "page": page["pageNumber"]})
    return rows


def extract_program_structure(line_rows: list[dict[str, Any]]) -> dict[str, Any]:
    overview_rows, segments = segment_program_lines(line_rows)
    summary: dict[str, str] = {}
    other_requirements: list[str] = []
    sections: list[dict[str, Any]] = []

    for segment in segments:
        metric = parse_summary_metric(segment["heading"])
        if metric:
            summary[metric["key"]] = metric["value"]

        section_title = normalize_section_heading(segment["heading"])
        if section_title in RULE_SECTION_TITLES:
            rules = [_clean_line(row["text"]) for row in segment["rows"] if _clean_line(row["text"])]
            if section_title == "General Education (Andrews Core Experience)":
                if rules:
                    other_requirements.extend(rules)
                else:
                    other_requirements.append("Andrews Core Experience")
            else:
                other_requirements.extend(rules)
            continue

        sections.extend(parse_requirement_sections(segment, metric))

    if not other_requirements:
        other_requirements = extract_freeform_requirements(segments)

    return {
        "overview": _join_section_lines([row["text"] for row in overview_rows[:14]]),
        "summary": summary,
        "other_requirements": _dedupe_preserve_order(other_requirements),
        "sections": [section for section in sections if _section_has_content(section)],
    }


def build_program_profile(
    entry: dict[str, Any],
    structure: dict[str, Any],
    program_pages: list[int],
) -> dict[str, Any]:
    return {
        "program": entry["title"],
        "program_type": entry.get("program_type"),
        "award": entry.get("award"),
        "pdf_pages": program_pages,
        "overview": structure["overview"],
        "summary": structure["summary"],
        "sections": [serialize_section(section) for section in structure["sections"]],
        "other_requirements": structure["other_requirements"],
    }


def serialize_section(section: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "section": section["title"],
        "type": section["type"],
        "pdf_pages": sorted(section["pages"]),
    }
    if section.get("required_credits") is not None:
        payload["required_credits"] = section["required_credits"]
    if section.get("courses"):
        payload["courses"] = section["courses"]
    if section.get("options"):
        payload["options"] = section["options"]
    if section.get("rules"):
        payload["rules"] = section["rules"]
    if section.get("subsection_titles"):
        payload["subsection_titles"] = section["subsection_titles"]
    return payload


def segment_program_lines(
    line_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    overview_rows: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    current_segment: dict[str, Any] | None = None

    for row in line_rows:
        line = row["text"]
        if is_break_heading(line):
            break

        if is_relevant_heading(line):
            current_segment = {
                "heading": line,
                "rows": [],
                "pages": {row["page"]},
            }
            segments.append(current_segment)
            continue

        if current_segment is None:
            overview_rows.append(row)
            continue

        current_segment["rows"].append(row)
        current_segment["pages"].add(row["page"])

    return overview_rows, segments


def parse_requirement_sections(
    segment: dict[str, Any],
    metric: dict[str, str] | None,
) -> list[dict[str, Any]]:
    base_title = normalize_section_heading(segment["heading"])
    base_required_credits = metric["value"] if metric else None

    if base_title in GROUPED_SECTION_TITLES:
        return parse_grouped_section(segment, base_title, base_required_credits)

    base_type = infer_section_type(base_title)
    section = _new_section(
        title=base_title,
        section_type=base_type,
        required_credits=base_required_credits,
        pages=segment["pages"],
    )
    sections = [section]
    current = section

    for row in segment["rows"]:
        line = row["text"]
        choose_heading = normalize_choose_heading(line)
        if choose_heading:
            if (
                current is section
                and current["type"] == "choose_from_pool"
                and not current["courses"]
                and not current["options"]
                and not current["rules"]
            ):
                inline_credits = extract_inline_credits(line)
                if inline_credits and current["required_credits"] is None:
                    current["required_credits"] = inline_credits
                current["rules"].append(_clean_line(line).rstrip(":"))
                current["pages"].add(row["page"])
                continue

            current = _new_section(
                title=choose_heading,
                section_type="choose_from_pool",
                required_credits=extract_inline_credits(line),
                pages={row["page"]},
            )
            sections.append(current)
            continue

        courses = parse_course_entries(line)
        if courses:
            target_key = "options" if current["type"] == "choose_from_pool" else "courses"
            current[target_key].extend(courses)
            current["pages"].add(row["page"])
            continue

        cleaned = _clean_line(line)
        if cleaned:
            current["rules"].append(cleaned)
            current["pages"].add(row["page"])

    return sections


def parse_grouped_section(
    segment: dict[str, Any],
    base_title: str,
    base_required_credits: str | None,
) -> list[dict[str, Any]]:
    grouped = _new_section(
        title=base_title,
        section_type="grouped_requirements",
        required_credits=base_required_credits,
        pages=segment["pages"],
    )
    sections = [grouped]

    pending_subgroup: str | None = None
    current = _new_section(
        title=f"{base_title} - Required",
        section_type="required_courses",
        required_credits=None,
        pages=set(),
    )

    for row in segment["rows"]:
        line = row["text"]
        subgroup_title = normalize_subgroup_heading(line)
        if subgroup_title:
            pending_subgroup = subgroup_title
            continue

        choose_heading = normalize_choose_heading(line)
        if choose_heading:
            title = (
                f"{base_title} - {normalize_choice_label(pending_subgroup, choose_heading)}"
                if pending_subgroup
                else choose_heading
            )
            current = _new_section(
                title=title,
                section_type="choose_from_pool",
                required_credits=extract_inline_credits(line),
                pages={row["page"]},
            )
            sections.append(current)
            grouped["subsection_titles"].append(current["title"])
            pending_subgroup = None
            continue

        courses = parse_course_entries(line)
        if courses:
            if pending_subgroup:
                current = _new_section(
                    title=f"{base_title} - {pending_subgroup}",
                    section_type="required_courses",
                    required_credits=None,
                    pages={row["page"]},
                )
                sections.append(current)
                grouped["subsection_titles"].append(current["title"])
                pending_subgroup = None
            elif current not in sections:
                sections.append(current)
                grouped["subsection_titles"].append(current["title"])

            target_key = "options" if current["type"] == "choose_from_pool" else "courses"
            current[target_key].extend(courses)
            current["pages"].add(row["page"])
            continue

        cleaned = _clean_line(line)
        if cleaned:
            if pending_subgroup:
                current = _new_section(
                    title=f"{base_title} - {pending_subgroup}",
                    section_type="rule",
                    required_credits=None,
                    pages={row["page"]},
                )
                sections.append(current)
                grouped["subsection_titles"].append(current["title"])
                pending_subgroup = None
            current["rules"].append(cleaned)
            current["pages"].add(row["page"])

    if current["title"] == f"{base_title} - Required" and not _section_has_content(current):
        sections = [section for section in sections if section is not current]
    elif current["title"] == f"{base_title} - Required" and current not in sections:
        sections.append(current)
        grouped["subsection_titles"].append(current["title"])

    grouped["subsection_titles"] = _dedupe_preserve_order(grouped["subsection_titles"])
    return sections


def format_program_profile_chunk(
    *,
    program_profile: dict[str, Any],
    bulletin_label: str,
    source_chunk_ids: list[str],
) -> str:
    lines = [
        f"Program Profile: {program_profile['program']}",
        f"Bulletin: {bulletin_label}",
        f"Program Type: {program_profile.get('program_type') or 'program'}",
    ]
    if program_profile.get("award"):
        lines.append(f"Award: {program_profile['award']}")
    lines.append(f"PDF Pages: {', '.join(str(page) for page in program_profile['pdf_pages'])}")

    if program_profile.get("overview"):
        lines.extend(["", "Overview", program_profile["overview"]])

    if program_profile.get("summary"):
        lines.extend(["", "Credit Summary"])
        for key, value in program_profile["summary"].items():
            lines.append(f"- {humanize_summary_key(key)}: {value}")

    if program_profile.get("sections"):
        lines.extend(["", "Requirements Snapshot"])
        for section in program_profile["sections"]:
            lines.append(f"- {summarize_section_for_search(section)}")

    if program_profile.get("other_requirements"):
        lines.extend(["", "Other Requirements"])
        for requirement in program_profile["other_requirements"]:
            lines.append(f"- {requirement}")

    lines.extend(
        [
            "",
            "Structured Program Data",
            json.dumps(program_profile, ensure_ascii=True, separators=(",", ":")),
            "",
            f"Source Raw Chunks: {', '.join(source_chunk_ids)}",
        ]
    )
    return "\n".join(lines).strip()


def summarize_section_for_search(section: dict[str, Any]) -> str:
    parts = [section["section"]]
    if section.get("required_credits") is not None:
        parts.append(f"credits={section['required_credits']}")
    if section.get("courses"):
        codes = ", ".join(course["course"] for course in section["courses"][:16])
        parts.append(f"courses={codes}")
    if section.get("options"):
        codes = ", ".join(option["course"] for option in section["options"][:16])
        parts.append(f"options={codes}")
    if section.get("subsection_titles"):
        parts.append(f"subsections={', '.join(section['subsection_titles'][:6])}")
    if section.get("rules"):
        parts.append(f"rules={'; '.join(section['rules'][:2])}")
    return " | ".join(parts)


def parse_summary_metric(line: str) -> dict[str, str] | None:
    match = re.match(r"^(?P<label>.+?)\s*-\s*(?P<value>.+)$", line)
    if not match:
        return None

    label = _clean_line(match.group("label"))
    value = _clean_line(match.group("value"))
    if not label or not value:
        return None

    return {
        "label": label,
        "value": value,
        "key": summarize_label_to_key(label),
    }


def summarize_label_to_key(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if slug.endswith("_credits"):
        return slug
    return f"{slug}_credits"


def humanize_summary_key(key: str) -> str:
    label = key[:-8] if key.endswith("_credits") else key
    return label.replace("_", " ").title() + (" Credits" if key.endswith("_credits") else "")


def normalize_section_heading(line: str) -> str:
    metric = parse_summary_metric(line)
    label = metric["label"] if metric else line
    normalized = _clean_line(label)
    lowered = normalized.lower()

    mapping = {
        "major": "Major Courses",
        "core": "Core Courses",
        "business core": "Business Core Courses",
        "business": "Business Courses",
        "flight": "Flight Courses",
        "aviation maintenance": "Aviation Maintenance Courses",
        "electives": "Electives",
        "math electives": "Math Electives",
        "cognates": "Cognates",
        "application area": "Application Area",
        "applied area minor": "Applied Area Minor",
    }
    return mapping.get(lowered, normalized)


def infer_section_type(title: str) -> str:
    lowered = title.lower()
    if title in RULE_SECTION_TITLES:
        return "rule"
    if "elective" in lowered:
        return "choose_from_pool"
    if title in GROUPED_SECTION_TITLES:
        return "grouped_requirements"
    if "application area" in lowered or "minor" in lowered:
        return "rule"
    return "required_courses"


def normalize_choose_heading(line: str) -> str | None:
    lowered = line.lower()
    if not lowered.startswith("choose "):
        return None

    cleaned = re.sub(r"\s*Credits\s*/\s*Units:\s*.+$", "", line, flags=re.IGNORECASE)
    cleaned = cleaned.rstrip(":")
    cleaned = re.sub(r"\bof the following courses?\b", "courses", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bof the following\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned.title()


def normalize_subgroup_heading(line: str) -> str | None:
    lowered = line.strip().lower()
    if lowered in SUBGROUP_CHOICE_TITLES:
        return SUBGROUP_CHOICE_TITLES[lowered]
    return None


def normalize_choice_label(group_title: str | None, choose_heading: str) -> str:
    if not group_title:
        return choose_heading

    lowered = choose_heading.lower()
    if "at least one" in lowered:
        suffix = "Choose At Least One"
    elif "choose one" in lowered:
        suffix = "Choose One"
    elif "choose two" in lowered:
        suffix = "Choose Two"
    elif "choose three" in lowered:
        suffix = "Choose Three"
    else:
        suffix = "Choice"
    return f"{group_title} {suffix}"


def extract_inline_credits(line: str) -> str | None:
    match = re.search(r"Credits\s*/\s*Units:\s*(?P<value>.+)$", line, flags=re.IGNORECASE)
    if match:
        return _clean_line(match.group("value"))
    return None


def parse_course_entries(line: str) -> list[dict[str, str]]:
    matches = list(COURSE_ENTRY_PATTERN.finditer(line))
    if not matches:
        return []

    entries = []
    for match in matches:
        entries.append(
            {
                "course": _clean_line(match.group("course")),
                "title": _clean_line(match.group("title")).rstrip(" ."),
                "credits": _clean_line(match.group("credits")).rstrip(" ."),
            }
        )
    return entries


def extract_freeform_requirements(segments: list[dict[str, Any]]) -> list[str]:
    requirements: list[str] = []
    for segment in segments:
        title = normalize_section_heading(segment["heading"])
        if title not in RULE_SECTION_TITLES:
            continue
        if title == "General Education (Andrews Core Experience)":
            requirements.append("Andrews Core Experience")
        for row in segment["rows"]:
            cleaned = _clean_line(row["text"])
            if cleaned:
                requirements.append(cleaned)
    return _dedupe_preserve_order(requirements)


def is_relevant_heading(line: str) -> bool:
    return any(line.startswith(prefix) for prefix in RELEVANT_SECTION_PREFIXES)


def is_break_heading(line: str) -> bool:
    return any(line.startswith(prefix) for prefix in BREAK_SECTION_PREFIXES)


def normalize_program_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_entry_title(title: str) -> str:
    title = _clean_line(title)
    for ignored in IGNORED_TOC_LINES:
        prefix = f"{ignored} "
        if title.lower().startswith(prefix):
            return title[len(prefix):].strip()
    return title


def _clean_line(line: str) -> str:
    line = line.replace("\u00ad", "")
    line = re.sub(r"[ \t]+", " ", line)
    return line.strip()


def _find_title_match(text: str, title: str) -> re.Match[str] | None:
    tokens = re.findall(r"[A-Za-z0-9]+", title)
    if not tokens:
        return None
    pattern = r"\b" + r"\W+".join(re.escape(token) for token in tokens) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE)


def _join_section_lines(lines: list[str]) -> str:
    normalized: list[str] = []
    for line in lines:
        if line == "\u2022":
            continue
        if normalized and normalized[-1].endswith("-"):
            normalized[-1] = normalized[-1][:-1] + line
            continue
        normalized.append(line)
    return "\n".join(normalized).strip()


def _source_chunk_ids_for_pages(raw_rows: list[dict[str, Any]], pages: list[int]) -> list[str]:
    page_set = set(pages)
    return [
        row["chunkId"]
        for row in raw_rows
        if row.get("sourceType") == "pdf"
        and set(row.get("pageOccurrence") or []).intersection(page_set)
    ]


def _new_section(
    *,
    title: str,
    section_type: str,
    required_credits: str | None,
    pages: set[int],
) -> dict[str, Any]:
    return {
        "title": title,
        "type": section_type,
        "required_credits": required_credits,
        "courses": [],
        "options": [],
        "rules": [],
        "subsection_titles": [],
        "pages": set(pages),
    }


def _section_has_content(section: dict[str, Any]) -> bool:
    return bool(
        section.get("courses")
        or section.get("options")
        or section.get("rules")
        or section.get("subsection_titles")
        or section.get("required_credits") is not None
    )


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
