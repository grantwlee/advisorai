import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

from database import engine

load_dotenv()

DEFAULT_PROCESSED_DIR = "data/bulletins/processed"
PROCESSED_DIR = os.getenv("RETRIEVAL_DATA_DIR", DEFAULT_PROCESSED_DIR)
JSONL_PATH = Path(PROCESSED_DIR) / "bulletin_chunks.jsonl"


def parse_chunk_index(chunk_id: str) -> int | None:
    if ":" not in chunk_id:
        return None
    _, suffix = chunk_id.split(":", 1)
    if suffix.isdigit():
        return int(suffix)
    return None


def create_table_and_index(conn, dialect: str) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS bulletin_chunks (
                id BIGSERIAL PRIMARY KEY,
                bulletin_id TEXT,
                source_type TEXT DEFAULT 'pdf',
                bulletin_year TEXT,
                program TEXT,
                section_title TEXT,
                page_number INTEGER,
                chunk_index INTEGER,
                chunk_hash TEXT UNIQUE,
                chunk_text TEXT NOT NULL
            )
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_bulletin_chunks_tsv
            ON bulletin_chunks
            USING GIN (to_tsvector('english', chunk_text))
            """
        )
    )


def load_rows(conn) -> tuple[int, int]:
    inserted = 0
    skipped = 0

    insert_sql = text(
        """
        INSERT INTO bulletin_chunks (
            bulletin_id,
            source_type,
            bulletin_year,
            program,
            section_title,
            page_number,
            chunk_index,
            chunk_hash,
            chunk_text
        ) VALUES (
            :bulletin_id,
            'pdf',
            :bulletin_year,
            NULL,
            NULL,
            :page_number,
            :chunk_index,
            :chunk_hash,
            :chunk_text
        )
        ON CONFLICT (chunk_hash) DO NOTHING
        """
    )

    with JSONL_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)
            page_occurrence = row.get("pageOccurrence") or []
            page_number = page_occurrence[0] if page_occurrence else None

            params = {
                "bulletin_id": row.get("bulletin"),
                "bulletin_year": row.get("bulletin"),
                "page_number": page_number,
                "chunk_index": parse_chunk_index(row.get("chunkId", "")),
                "chunk_hash": row.get("hash"),
                "chunk_text": row.get("chunk", ""),
            }

            result = conn.execute(insert_sql, params)
            if result.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

    return inserted, skipped


def main() -> None:
    if not JSONL_PATH.exists():
        raise FileNotFoundError(f"JSONL not found: {JSONL_PATH}")

    dialect = engine.dialect.name.lower()
    if dialect != "postgresql":
        raise RuntimeError(f"Unsupported database dialect: {dialect}. Loader is PostgreSQL-only.")

    print(f"DB dialect: {dialect}")
    print(f"Loading from: {JSONL_PATH}")

    with engine.begin() as conn:
        create_table_and_index(conn, dialect)
        inserted, skipped = load_rows(conn)

    print(f"Inserted: {inserted}")
    print(f"Skipped (existing): {skipped}")


if __name__ == "__main__":
    main()
