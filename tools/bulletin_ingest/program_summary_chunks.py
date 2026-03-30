from __future__ import annotations

import re
from typing import Any


TOC_PAGE_LIMIT = 20
TOC_ENTRY_PATTERN = re.compile(r"^(?P<title>.+?)\.{3,}\s*(?P<page>\d{1,4})$")
UNDERGRAD_DEGREE_PATTERN = re.compile(
    r"\b(AS|AT|BA|BA/BS|BS/BA|BBA|BBA/BA|BS|BSN|BSMLS|BSPH|BT|BHS|BID|BSA)\b",
    re.IGNORECASE,
)
EXCLUDED_TITLE_KEYWORDS = (
    "minor",
    "certificate",
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
    "Cognates -",
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
        source_text, source_pages = extract_program_source_text(pages, entry, next_entry)
        if not source_text or not source_pages:
            continue

        source_chunk_ids = [
            row["chunkId"]
            for row in raw_rows
            if row.get("sourceType") == "pdf"
            and set(row.get("pageOccurrence") or []).intersection(source_pages)
        ]
        if not source_chunk_ids:
            continue

        chunk_text = format_program_summary_chunk(
            title=entry["title"],
            bulletin_label=bulletin_label,
            source_pages=source_pages,
            source_chunk_ids=source_chunk_ids,
            source_text=source_text,
        )
        if not chunk_text:
            continue

        summary_rows.append(
            {
                "chunk": chunk_text,
                "pageOccurrence": source_pages,
                "charCount": len(chunk_text),
                "sourceType": "program_summary",
                "program": entry["title"],
                "sectionTitle": entry["title"],
                "sourcePageOccurrence": source_pages,
                "sourceChunkIds": source_chunk_ids,
            }
        )

    return summary_rows


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
                if is_program_title(title):
                    entries.append(
                        {
                            "title": title,
                            "page": start_page,
                            "order": order,
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


def is_program_title(title: str) -> bool:
    lowered = title.lower()
    if any(keyword in lowered for keyword in EXCLUDED_TITLE_KEYWORDS):
        return False
    return bool(UNDERGRAD_DEGREE_PATTERN.search(title))


def extract_program_source_text(
    pages: list[dict[str, Any]],
    entry: dict[str, Any],
    next_entry: dict[str, Any] | None,
) -> tuple[str, list[int]]:
    pages_by_number = {page["pageNumber"]: page["text"] for page in pages}
    last_page = pages[-1]["pageNumber"] if pages else entry["page"]
    end_page = next_entry["page"] if next_entry else last_page

    source_pages: list[int] = []
    parts: list[str] = []
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
            source_pages.append(page_number)
            parts.append(sliced)

    return "\n\n".join(parts).strip(), source_pages


def format_program_summary_chunk(
    *,
    title: str,
    bulletin_label: str,
    source_pages: list[int],
    source_chunk_ids: list[str],
    source_text: str,
) -> str:
    overview, sections = extract_summary_sections(source_text)
    lines = [
        f"Program Summary: {title}",
        f"Bulletin: {bulletin_label}",
        f"Source Pages: {', '.join(str(page) for page in source_pages)}",
        f"Source Raw Chunks: {', '.join(source_chunk_ids)}",
    ]

    if overview:
        lines.extend(["", "Overview", overview])

    for section in sections:
        lines.extend(["", section["title"]])
        if section["body"]:
            lines.append(section["body"])

    return "\n".join(lines).strip()


def extract_summary_sections(source_text: str) -> tuple[str, list[dict[str, str]]]:
    lines = [_clean_line(line) for line in source_text.splitlines()]
    lines = [line for line in lines if line and line != "\u2022"]

    overview_lines: list[str] = []
    sections: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    seen_section = False

    for line in lines:
        if is_break_heading(line):
            break

        if is_relevant_heading(line):
            current_section = {"title": line, "lines": []}
            sections.append(current_section)
            seen_section = True
            continue

        if not seen_section:
            overview_lines.append(line)
            continue

        if current_section is not None:
            current_section["lines"].append(line)

    formatted_sections = []
    for section in sections:
        body_lines = [line for line in section["lines"] if line]
        formatted_sections.append(
            {
                "title": section["title"],
                "body": _join_section_lines(body_lines) if body_lines else "",
            }
        )

    overview = _join_section_lines(overview_lines[:12]) if overview_lines else ""
    return overview, formatted_sections


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
