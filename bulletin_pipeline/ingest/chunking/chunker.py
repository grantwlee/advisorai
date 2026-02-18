import hashlib
import re
from dataclasses import dataclass


@dataclass
class Chunk:
    program: str
    section_title: str
    bulletin_year: str
    page_number: int | None
    chunk_index: int
    chunk_hash: str
    chunk_text: str


PROGRAM_HINTS = [
    "Computer Science",
    "Administration",
    "Aviation",
    "Engineering",
    "Information Systems",
    "Business",
    "Nursing",
    "Accounting",
    "MBA",
]


def infer_program(text: str) -> str:
    t = text.lower()
    for p in PROGRAM_HINTS:
        if p.lower() in t:
            return p
    return "Unknown"


def split_into_chunks(
    text: str,
    target_words: int = 500,
    max_words: int = 800
    ) -> list[str]:
    # Sentence-ish splitting
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())

    chunks: list[str] = []
    current: list[str] = []
    word_count = 0

    for s in sentences:
        w = len(s.split())

        if word_count + w > max_words and current:
            chunks.append(" ".join(current).strip())
            current = [s]
            word_count = w
        else:
            current.append(s)
            word_count += w

        if word_count >= target_words:
            chunks.append(" ".join(current).strip())
            current = []
            word_count = 0

    # Flush remaining content
    if current:
        chunks.append(" ".join(current).strip())

    # Drop tiny chunks
    return [c for c in chunks if len(c.split()) >= 80]


def make_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", errors="ignore"))
    return h.hexdigest()