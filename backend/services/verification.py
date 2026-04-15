import re


CITATION_PATTERN = re.compile(r"\[([^\[\]]+)\]")
PLANNING_CONTEXT_CITATION_ID = "planning_context"
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}


def split_sentences(answer: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", answer.strip())
    if not normalized:
        return []
    pieces = re.split(r"(?<=[.!?])\s+", normalized)
    return [piece.strip() for piece in pieces if piece.strip()]


def extract_citation_ids(text: str) -> list[str]:
    citations: list[str] = []
    for match in CITATION_PATTERN.findall(text):
        for part in match.split(","):
            cleaned = part.strip()
            if cleaned:
                citations.append(cleaned)
    return citations


def strip_citations(text: str) -> str:
    return CITATION_PATTERN.sub("", text).strip()


def tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in STOPWORDS and len(token) > 2
    }


def explicit_year_mentions(answer: str) -> set[str]:
    found = set()
    visible_text = strip_citations(answer)
    for match in re.findall(r"(20\d{2}-20\d{2}|\d{2}-\d{2})", visible_text):
        if len(match) == 5:
            start, end = match.split("-")
            found.add(f"20{start}-20{end}")
        else:
            found.add(match)
    return found


def planning_context_text(planning_context: dict | None) -> str:
    if not planning_context:
        return ""

    completed_codes = planning_context.get("completed_course_codes", [])
    in_progress_codes = planning_context.get("in_progress_course_codes", [])
    planned_codes = planning_context.get("planned_course_codes", [])
    remaining_core_codes = planning_context.get("remaining_core_course_codes", [])
    remaining_required_cognate_codes = planning_context.get(
        "remaining_required_cognate_course_codes",
        [],
    )

    parts = [
        f"program {planning_context.get('program', '')}",
        f"bulletin year {planning_context.get('bulletin_year', '')}",
        f"scope note {planning_context.get('scope_note', '')}",
        f"completed course count {len(completed_codes)}",
        f"in progress course count {len(in_progress_codes)}",
        f"planned course count {len(planned_codes)}",
        f"completed credits {planning_context.get('completed_credits', '')}",
        f"in progress credits {planning_context.get('in_progress_credits', '')}",
        f"planned credits {planning_context.get('planned_credits', '')}",
        f"remaining requirement count {planning_context.get('remaining_requirement_count', '')}",
        f"remaining credits {planning_context.get('remaining_credits', '')}",
        f"choose three remaining count {planning_context.get('choose_three_remaining_count', '')}",
        f"remaining elective credits {planning_context.get('remaining_elective_credits', '')}",
        f"statistics requirement remaining {planning_context.get('statistics_requirement_remaining', '')}",
        f"science requirement remaining {planning_context.get('science_requirement_remaining', '')}",
        f"choose one requirement remaining {planning_context.get('choose_one_requirement_remaining', '')}",
    ]
    if completed_codes:
        parts.append("completed courses " + " ".join(completed_codes))
    if in_progress_codes:
        parts.append("in progress courses " + " ".join(in_progress_codes))
    if planned_codes:
        parts.append("planned courses " + " ".join(planned_codes))
    if remaining_core_codes:
        parts.append("remaining core courses " + " ".join(remaining_core_codes))
    if remaining_required_cognate_codes:
        parts.append(
            "remaining required cognate courses " + " ".join(remaining_required_cognate_codes)
        )
    if planning_context.get("statistics_option_codes"):
        parts.append(
            "statistics options "
            + " ".join(planning_context.get("statistics_option_codes", []))
        )
    if planning_context.get("science_option_codes"):
        parts.append(
            "science options " + " ".join(planning_context.get("science_option_codes", []))
        )
    if planning_context.get("choose_one_option_codes"):
        parts.append(
            "choose one options " + " ".join(planning_context.get("choose_one_option_codes", []))
        )

    for row in planning_context.get("in_progress_courses", []):
        parts.append(
            "in progress course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
        )
    for row in planning_context.get("completed_courses", []):
        parts.append(
            "completed course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
        )
    for row in planning_context.get("planned_courses", []):
        parts.append(
            "planned course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
        )
    for row in planning_context.get("remaining_core_courses", []):
        parts.append(
            "remaining core course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
        )
    for row in planning_context.get("remaining_required_cognate_courses", []):
        parts.append(
            "remaining required cognate course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
        )
    for row in planning_context.get("choose_three_remaining_options", []):
        parts.append(
            "choose three remaining option "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
        )
    for row in planning_context.get("recommended_next_courses", []):
        parts.append(
            "recommended next course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')} "
            f"{row.get('category', '')} {row.get('rationale', '')}"
        )

    return "\n".join(part for part in parts if part.strip())


def verify_answer(
    answer: str,
    retrieved_chunks: list[dict],
    planning_context: dict | None = None,
) -> dict:
    retrieved_by_id = {chunk["chunkId"]: chunk for chunk in retrieved_chunks}
    planning_tokens = tokenize(planning_context_text(planning_context))
    sentences = split_sentences(answer)
    if not sentences:
        return {
            "passed": False,
            "issues": ["Answer is empty."],
            "sentences": [],
            "cited_years": [],
        }

    issues: list[str] = []
    sentence_results: list[dict] = []
    answer_citation_ids = extract_citation_ids(answer)

    valid_answer_citation_ids: list[str] = []
    missing_answer_ids: list[str] = []
    for chunk_id in answer_citation_ids:
        if chunk_id in retrieved_by_id or (
            chunk_id == PLANNING_CONTEXT_CITATION_ID and planning_context is not None
        ):
            if chunk_id not in valid_answer_citation_ids:
                valid_answer_citation_ids.append(chunk_id)
        elif chunk_id not in missing_answer_ids:
            missing_answer_ids.append(chunk_id)

    if missing_answer_ids:
        issues.append(
            "Answer cites chunks that were not retrieved: "
            + ", ".join(missing_answer_ids)
        )

    if not valid_answer_citation_ids:
        issues.append("Answer must include at least one valid citation.")

    for sentence in sentences:
        sentence_citation_ids = extract_citation_ids(sentence)
        sentence_body = strip_citations(sentence)
        citation_ids = sentence_citation_ids or valid_answer_citation_ids
        result = {
            "sentence": sentence,
            "citations": citation_ids,
            "supported": False,
        }

        missing_ids = [
            chunk_id
            for chunk_id in sentence_citation_ids
            if chunk_id not in retrieved_by_id
            and not (
                chunk_id == PLANNING_CONTEXT_CITATION_ID and planning_context is not None
            )
        ]
        if missing_ids:
            issues.append(
                f"Sentence cites chunks that were not retrieved: {', '.join(missing_ids)}"
            )
            sentence_results.append(result)
            continue

        if not sentence_body:
            issues.append(f"Sentence contains only citations: {sentence}")
            sentence_results.append(result)
            continue

        if not citation_ids:
            sentence_results.append(result)
            continue

        body_tokens = tokenize(sentence_body)
        cited_tokens = set()
        for chunk_id in citation_ids:
            if chunk_id == PLANNING_CONTEXT_CITATION_ID:
                cited_tokens |= planning_tokens
                continue
            chunk = retrieved_by_id[chunk_id]
            cited_tokens |= tokenize(chunk.get("chunk", ""))

        overlap = body_tokens & cited_tokens
        supported = not body_tokens or len(overlap) >= min(3, max(1, len(body_tokens) // 3))
        if not supported:
            issues.append(
                "Sentence is not sufficiently supported by cited text: "
                f"{strip_citations(sentence)}"
            )

        result["supported"] = supported
        result["overlap_tokens"] = sorted(overlap)
        sentence_results.append(result)

    cited_years = {
        chunk["bulletin"]
        for chunk_id in extract_citation_ids(answer)
        if chunk_id != PLANNING_CONTEXT_CITATION_ID and (chunk := retrieved_by_id.get(chunk_id))
    }
    expanded_cited_years = set()
    for year in cited_years:
        if re.fullmatch(r"\d{2}-\d{2}", year):
            start, end = year.split("-")
            expanded_cited_years.add(f"20{start}-20{end}")
        expanded_cited_years.add(year)

    if len(cited_years) > 1:
        mentions = explicit_year_mentions(answer)
        if not mentions.intersection(expanded_cited_years):
            issues.append(
                "Answer cites multiple bulletin years but does not explicitly qualify the year."
            )

    return {
        "passed": not issues,
        "issues": issues,
        "sentences": sentence_results,
        "cited_years": sorted(cited_years),
    }
