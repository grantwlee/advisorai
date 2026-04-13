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
    completed_courses = planning_context.get("completed_courses", [])
    in_progress_codes = planning_context.get("in_progress_course_codes", [])
    planned_codes = planning_context.get("planned_course_codes", [])

    parts = [
        f"program {planning_context.get('program', '')}",
        f"bulletin year {planning_context.get('bulletin_year', '')}",
        f"completed course count {len(completed_codes)}",
        f"in progress course count {len(in_progress_codes)}",
        f"planned course count {len(planned_codes)}",
        f"completed credits {planning_context.get('completed_credits', '')}",
        f"in progress credits {planning_context.get('in_progress_credits', '')}",
        f"planned credits {planning_context.get('planned_credits', '')}",
    ]
    if completed_codes:
        parts.append("completed courses " + " ".join(completed_codes))
    for row in completed_courses:
        parts.append(
            "completed course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
        )
    if in_progress_codes:
        parts.append("in progress courses " + " ".join(in_progress_codes))
    if planned_codes:
        parts.append("planned courses " + " ".join(planned_codes))

    for row in planning_context.get("in_progress_courses", []):
        parts.append(
            "in progress course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
        )
    for row in planning_context.get("planned_courses", []):
        parts.append(
            "planned course "
            f"{row.get('code', '')} {row.get('title', '')} {row.get('credits', '')}"
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
    issues: list[str] = []
    sentence_results: list[dict] = []

    for sentence in sentences:
        citation_ids = extract_citation_ids(sentence)
        sentence_body = strip_citations(sentence)
        result = {
            "sentence": sentence,
            "citations": citation_ids,
            "supported": False,
        }

        if not citation_ids:
            issues.append(f"Missing citation in sentence: {sentence}")
            sentence_results.append(result)
            continue

        missing_ids = [
            chunk_id
            for chunk_id in citation_ids
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
        "passed": not issues and bool(sentences),
        "issues": issues or ([] if sentences else ["Answer is empty."]),
        "sentences": sentence_results,
        "cited_years": sorted(cited_years),
    }
