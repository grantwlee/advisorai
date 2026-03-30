import json
import os
import re
from functools import lru_cache
from typing import Iterable

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import engine
from services.year_utils import normalize_bulletin_year


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_PROCESSED_DIR = "data/bulletins/processed"
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
DEFAULT_QUERY_SOURCE_TYPES = ("program_summary",)

def tokenize_program(program: str | None) -> list[str]:
    if not program:
        return []
    return [
        token
        for token in re.findall(r"[a-z0-9]+", program.lower())
        if token not in STOPWORDS and len(token) > 2
    ]


class RetrievalService:
    def __init__(self) -> None:
        processed_dir = os.getenv("RETRIEVAL_DATA_DIR", DEFAULT_PROCESSED_DIR)
        self.processed_dir = processed_dir
        self.faiss_path = os.path.join(processed_dir, "bulletin_index.faiss")
        self.jsonl_path = os.path.join(processed_dir, "bulletin_chunks.jsonl")
        self.model = SentenceTransformer(MODEL_NAME)
        self.index = faiss.read_index(self.faiss_path)

        with open(self.jsonl_path, "r", encoding="utf-8") as handle:
            self.metadata = [json.loads(line) for line in handle]

        self.metadata_by_hash = {
            row.get("hash"): row for row in self.metadata if row.get("hash")
        }
        self.metadata_by_chunk_id = {
            row.get("chunkId"): row for row in self.metadata if row.get("chunkId")
        }

    def _program_matches(self, text_value: str, program: str | None) -> bool:
        tokens = tokenize_program(program)
        if not tokens:
            return True

        haystack = text_value.lower()
        token_hits = sum(1 for token in tokens if token in haystack)
        return token_hits >= min(2, len(tokens))

    def _normalize_source_types(
        self,
        source_types: Iterable[str] | None,
    ) -> set[str] | None:
        if source_types is None:
            return None

        normalized = {
            value.strip().lower()
            for value in source_types
            if isinstance(value, str) and value.strip()
        }
        return normalized or None

    def _source_type_matches(
        self,
        row: dict,
        allowed_source_types: set[str] | None,
    ) -> bool:
        if allowed_source_types is None:
            return True
        return (row.get("sourceType") or "pdf").lower() in allowed_source_types

    def _metadata_to_result(
        self,
        row: dict,
        *,
        semantic_score: float = 0.0,
        keyword_score: float = 0.0,
        keyword_matched: bool = False,
    ) -> dict:
        return {
            "chunkId": row["chunkId"],
            "bulletin": row["bulletin"],
            "pageOccurrence": row.get("pageOccurrence") or [],
            "sourcePageOccurrence": row.get("sourcePageOccurrence") or [],
            "sourceChunkIds": row.get("sourceChunkIds") or [],
            "preview": row["chunk"][:300],
            "chunk": row["chunk"],
            "sourcePdf": row.get("sourcePdf"),
            "sourceType": row.get("sourceType"),
            "program": row.get("program"),
            "sectionTitle": row.get("sectionTitle"),
            "hash": row.get("hash"),
            "semanticScore": float(semantic_score),
            "keywordScore": float(keyword_score),
            "keywordMatched": keyword_matched,
        }

    def semantic_search(
        self,
        query: str,
        *,
        k: int = 10,
        bulletin_year: str | None = None,
        program: str | None = None,
        source_types: Iterable[str] | None = None,
    ) -> list[dict]:
        target_year = normalize_bulletin_year(bulletin_year)
        allowed_source_types = self._normalize_source_types(source_types)
        effective_query = query.strip()
        if program:
            effective_query = f"{program} {effective_query}".strip()

        q_vec = self.model.encode([effective_query], normalize_embeddings=True)
        if allowed_source_types is None:
            search_k = min(max(k * 8, k), len(self.metadata))
        else:
            search_k = len(self.metadata)
        scores, indices = self.index.search(np.array(q_vec, dtype=np.float32), search_k)

        results: list[dict] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue

            row = self.metadata[idx]
            if target_year and normalize_bulletin_year(row.get("bulletin")) != target_year:
                continue
            if not self._source_type_matches(row, allowed_source_types):
                continue
            searchable_text = "\n".join(
                part
                for part in (
                    row.get("program"),
                    row.get("sectionTitle"),
                    row.get("chunk"),
                )
                if part
            )
            if not self._program_matches(searchable_text, program):
                continue

            results.append(self._metadata_to_result(row, semantic_score=float(score)))
            if len(results) >= k:
                break

        return results

    def keyword_search(
        self,
        query: str,
        *,
        k: int = 10,
        bulletin_year: str | None = None,
        program: str | None = None,
        source_types: Iterable[str] | None = None,
    ) -> list[dict]:
        clauses = [
            "to_tsvector('english', chunk_text) @@ plainto_tsquery('english', :q)"
        ]
        params: dict[str, object] = {"q": query, "k": int(k)}
        target_year = normalize_bulletin_year(bulletin_year)
        allowed_source_types = self._normalize_source_types(source_types)
        if target_year:
            clauses.append("bulletin_year = :bulletin_year")
            params["bulletin_year"] = target_year

        if allowed_source_types:
            clauses.append("LOWER(COALESCE(source_type, 'pdf')) = ANY(:source_types)")
            params["source_types"] = list(allowed_source_types)

        if program:
            clauses.append(
                "(LOWER(COALESCE(program, '')) LIKE :program_pattern "
                "OR LOWER(chunk_text) LIKE :program_pattern)"
            )
            params["program_pattern"] = f"%{program.lower()}%"

        sql = text(
            f"""
            SELECT
                chunk_hash,
                bulletin_year,
                chunk_text,
                ts_rank_cd(
                    to_tsvector('english', chunk_text),
                    plainto_tsquery('english', :q)
                ) AS keyword_score
            FROM bulletin_chunks
            WHERE {' AND '.join(clauses)}
            ORDER BY keyword_score DESC
            LIMIT :k
            """
        )

        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()

        results: list[dict] = []
        for row in rows:
            hash_key = row.get("chunk_hash")
            meta = self.metadata_by_hash.get(hash_key)
            if meta:
                results.append(
                    self._metadata_to_result(
                        meta,
                        keyword_score=float(row.get("keyword_score") or 0.0),
                        keyword_matched=True,
                    )
                )
                continue

            bulletin = row.get("bulletin_year", "unknown")
            chunk_id = f"{bulletin}:{hash_key[:8] if hash_key else 'unknown'}"
            chunk_text = row.get("chunk_text") or ""
            results.append(
                {
                    "chunkId": chunk_id,
                    "bulletin": bulletin,
                    "pageOccurrence": [],
                    "sourcePageOccurrence": [],
                    "sourceChunkIds": [],
                    "preview": chunk_text[:300],
                    "chunk": chunk_text,
                    "sourcePdf": None,
                    "sourceType": None,
                    "program": None,
                    "sectionTitle": None,
                    "hash": hash_key,
                    "semanticScore": 0.0,
                    "keywordScore": float(row.get("keyword_score") or 0.0),
                    "keywordMatched": True,
                }
            )

        return results

    def hybrid_search(
        self,
        query: str,
        *,
        k: int = 5,
        bulletin_year: str | None = None,
        program: str | None = None,
        source_types: Iterable[str] | None = None,
    ) -> list[dict]:
        semantic_top = self.semantic_search(
            query,
            k=max(k, 10),
            bulletin_year=bulletin_year,
            program=program,
            source_types=source_types,
        )
        try:
            keyword_top = self.keyword_search(
                query,
                k=max(k, 10),
                bulletin_year=bulletin_year,
                program=program,
                source_types=source_types,
            )
        except SQLAlchemyError:
            keyword_top = []

        merged: dict[str, dict] = {}
        for row in semantic_top:
            merged[row["chunkId"]] = dict(row)

        for row in keyword_top:
            existing = merged.get(row["chunkId"])
            if existing is None:
                merged[row["chunkId"]] = dict(row)
                continue

            existing["keywordMatched"] = True
            existing["keywordScore"] = max(
                float(existing.get("keywordScore") or 0.0),
                float(row.get("keywordScore") or 0.0),
            )

        results = []
        for row in merged.values():
            total_score = float(row.get("semanticScore") or 0.0)
            if row.get("keywordMatched"):
                total_score += 2.0
            row["score"] = round(total_score, 6)
            results.append(row)

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:k]

    def get_chunk(self, chunk_id: str) -> dict | None:
        row = self.metadata_by_chunk_id.get(chunk_id)
        if not row:
            return None
        return self._metadata_to_result(row)

    def get_chunks(self, chunk_ids: list[str]) -> list[dict]:
        chunks = []
        for chunk_id in chunk_ids:
            chunk = self.get_chunk(chunk_id)
            if chunk:
                chunks.append(chunk)
        return chunks


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    return RetrievalService()
