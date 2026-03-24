import re


CITATION_PATTERN = re.compile(r"\[([^\[\]]+)\]")
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


def verify_answer(answer: str, retrieved_chunks: list[dict]) -> dict:
    retrieved_by_id = {chunk["chunkId"]: chunk for chunk in retrieved_chunks}
    sentences = split_sentences(answer)
    issues: list[str] = []
    sentence_results: list[dict] = []

    for sentence in sentences:
        citation_ids = extract_citation_ids(sentence)
        result = {
            "sentence": sentence,
            "citations": citation_ids,
            "supported": False,
        }

        if not citation_ids:
            issues.append(f"Missing citation in sentence: {sentence}")
            sentence_results.append(result)
            continue

        missing_ids = [chunk_id for chunk_id in citation_ids if chunk_id not in retrieved_by_id]
        if missing_ids:
            issues.append(
                f"Sentence cites chunks that were not retrieved: {', '.join(missing_ids)}"
            )
            sentence_results.append(result)
            continue

        body_tokens = tokenize(strip_citations(sentence))
        cited_chunks = [retrieved_by_id[chunk_id] for chunk_id in citation_ids]
        cited_tokens = set()
        for chunk in cited_chunks:
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
        if (chunk := retrieved_by_id.get(chunk_id))
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
