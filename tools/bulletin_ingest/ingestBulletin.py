import os
import re
import json
import hashlib
from typing import List, Dict, Any, Tuple

import fitz  # PyMuPDF
import numpy as np
import faiss

from sentence_transformers import SentenceTransformer

try:
    from .program_summary_chunks import (
        build_program_summary_rows,
        build_structured_program_catalog,
    )
except ImportError:
    from program_summary_chunks import (
        build_program_summary_rows,
        build_structured_program_catalog,
    )


# ----------------------------
# Config
# ----------------------------
RAW_DIR = "data/bulletins/raw"
OUT_DIR = "data/bulletins/processed"

OUT_JSONL = os.path.join(OUT_DIR, "bulletin_chunks.jsonl")
OUT_INDEX_JSONL = os.path.join(OUT_DIR, "bulletin_index_metadata.jsonl")
OUT_MANIFEST = os.path.join(OUT_DIR, "bulletin_chunks_manifest.json")
OUT_FAISS = os.path.join(OUT_DIR, "bulletin_index.faiss")
OUT_PROGRAMS_JSON = os.path.join(OUT_DIR, "bulletin_program_structures.json")

# Header/footer removal:
# remove anything in the top X% and bottom Y% of a page
HEADER_CUT = 0.08   # top 8% of page height
FOOTER_CUT = 0.08   # bottom 8% of page height

# Chunking
MIN_CHARS = 1200
MAX_CHARS = 1500
CHUNK_OVERLAP_CHARS = 80

# Embeddings
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


# ----------------------------
# Helpers
# ----------------------------
def normalize_whitespace(text: str) -> str:
    text = text.replace("\u00ad", "")  # soft hyphen
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def stable_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()


def guess_bulletin_label(pdf_filename: str) -> str:
    """
    Try to infer a bulletin label from the file name.
    Example: 'Bulletin_23-24_PDF_FINAL (1).pdf' -> '23-24'
    Fallback: base filename without extension.
    """
    base = os.path.basename(pdf_filename)
    m = re.search(r"(\d{2}\s*-\s*\d{2})", base)
    if m:
        return m.group(1).replace(" ", "")
    # sometimes 2023–2024 style, try 4-digit years
    m2 = re.search(r"(20\d{2})\D+(20\d{2})", base)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}"
    return os.path.splitext(base)[0]


def extract_page_text_without_header_footer(doc: fitz.Document, page_index: int) -> str:
    """
    Extract text blocks and filter out blocks that fall into header/footer bands.
    Uses bounding boxes -> works better than raw text extraction for repeated headers/footers.
    """
    page = doc[page_index]
    page_height = page.rect.height

    header_y = page_height * HEADER_CUT
    footer_y = page_height * (1.0 - FOOTER_CUT)

    blocks = page.get_text("blocks")  # (x0,y0,x1,y1,"text",block_no,block_type)
    kept: List[Tuple[float, float, float, float, str]] = []

    for b in blocks:
        x0, y0, x1, y1, text, *_ = b
        if not text or not text.strip():
            continue

        # Filter header/footer by block vertical position
        if y1 <= header_y:
            continue
        if y0 >= footer_y:
            continue

        # also drop pure page numbers if they sneak in
        t = text.strip()
        if re.fullmatch(r"\d{1,4}", t):
            continue

        kept.append((x0, y0, x1, y1, t))

    ordered = order_text_blocks_for_reading(kept, page.rect.width)
    combined = "\n".join(text for *_, text in ordered)
    return normalize_whitespace(combined)


def order_text_blocks_for_reading(
    blocks: List[Tuple[float, float, float, float, str]],
    page_width: float,
) -> List[Tuple[float, float, float, float, str]]:
    if not blocks:
        return []

    midpoint = page_width / 2.0
    narrow_blocks = [block for block in blocks if (block[2] - block[0]) < page_width * 0.72]
    left_blocks = [block for block in narrow_blocks if ((block[0] + block[2]) / 2.0) < midpoint]
    right_blocks = [block for block in narrow_blocks if ((block[0] + block[2]) / 2.0) >= midpoint]
    has_two_columns = len(left_blocks) >= 3 and len(right_blocks) >= 3

    if not has_two_columns:
        return sorted(blocks, key=lambda block: (block[1], block[0]))

    column_top = min(block[1] for block in narrow_blocks)
    column_bottom = max(block[3] for block in narrow_blocks)

    leading_full: List[Tuple[float, float, float, float, str]] = []
    trailing_full: List[Tuple[float, float, float, float, str]] = []
    left_column: List[Tuple[float, float, float, float, str]] = []
    right_column: List[Tuple[float, float, float, float, str]] = []

    for block in blocks:
        x0, y0, x1, y1, _text = block
        center_x = (x0 + x1) / 2.0
        width = x1 - x0

        if width >= page_width * 0.72:
            if y0 <= column_top:
                leading_full.append(block)
            elif y1 >= column_bottom:
                trailing_full.append(block)
            elif center_x < midpoint:
                left_column.append(block)
            else:
                right_column.append(block)
            continue

        if center_x < midpoint:
            left_column.append(block)
        else:
            right_column.append(block)

    return (
        sorted(leading_full, key=lambda block: (block[1], block[0]))
        + sorted(left_column, key=lambda block: (block[1], block[0]))
        + sorted(right_column, key=lambda block: (block[1], block[0]))
        + sorted(trailing_full, key=lambda block: (block[1], block[0]))
    )


def make_chunks(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    pages: [{pageNumber: int, text: str}]
    Returns chunk dicts with pageOccurrence mapping.
    Chunking is done on the full cleaned document text, while tracking which pages contribute.
    """
    # Build a single document string but keep page spans
    full = []
    spans = []  # (start_idx, end_idx, pageNumber)
    cursor = 0

    for p in pages:
        t = p["text"]
        if not t:
            continue
        start = cursor
        full.append(t)
        cursor += len(t)
        end = cursor
        spans.append((start, end, p["pageNumber"]))
        # add separator
        full.append("\n\n")
        cursor += 2

    doc_text = "".join(full).strip()
    if not doc_text:
        return []

    chunks = []
    n = len(doc_text)
    step = MAX_CHARS - CHUNK_OVERLAP_CHARS
    start = 0
    seen_ranges: set[tuple[int, int]] = set()

    while start < n:
        end = min(start + MAX_CHARS, n)

        # Keep the tail within min/max by shifting the final window left.
        if end == n and (end - start) < MIN_CHARS and n > MIN_CHARS:
            start = max(0, n - MIN_CHARS)
            end = n

        range_key = (start, end)
        if range_key in seen_ranges:
            break
        seen_ranges.add(range_key)

        chunk_text = normalize_whitespace(doc_text[start:end])
        if len(chunk_text) < MIN_CHARS:
            break

        page_occurrence = sorted(
            {
                pg
                for span_start, span_end, pg in spans
                if not (end <= span_start or start >= span_end)
            }
        )

        chunks.append({
            "chunk": chunk_text,
            "pageOccurrence": page_occurrence,
            "charCount": len(chunk_text),
        })

        if end == n:
            break
        start += step

    return chunks


# ----------------------------
# Main pipeline
# ----------------------------
def ingest_bulletins():
    os.makedirs(OUT_DIR, exist_ok=True)

    pdfs = [os.path.join(RAW_DIR, f) for f in os.listdir(RAW_DIR) if f.lower().endswith(".pdf")]
    pdfs.sort()

    if not pdfs:
        raise FileNotFoundError(f"No PDFs found in: {RAW_DIR}")

    print(f"Found {len(pdfs)} PDF(s)")

    model = SentenceTransformer(MODEL_NAME)

    all_rows: List[Dict[str, Any]] = []
    indexed_rows: List[Dict[str, Any]] = []
    indexed_vectors: List[np.ndarray] = []
    structured_catalogs: List[Dict[str, Any]] = []

    chunk_counter = 0
    manifest = {
        "sourceDir": RAW_DIR,
        "outDir": OUT_DIR,
        "model": MODEL_NAME,
        "headerCutPct": HEADER_CUT,
        "footerCutPct": FOOTER_CUT,
        "minChars": MIN_CHARS,
        "maxChars": MAX_CHARS,
        "overlapChars": CHUNK_OVERLAP_CHARS,
        "bulletins": []
    }

    for pdf_path in pdfs:
        bulletin_label = guess_bulletin_label(pdf_path)
        doc = fitz.open(pdf_path)

        pages = []
        for pno in range(doc.page_count):
            text = extract_page_text_without_header_footer(doc, pno)
            pages.append({"pageNumber": pno + 1, "text": text})

        chunks = make_chunks(pages)

        raw_rows: List[Dict[str, Any]] = []
        for c in chunks:
            chunk_counter += 1
            chunk_id = f"{bulletin_label}:{chunk_counter:06d}"
            row = {
                "chunkId": chunk_id,
                "chunk": c["chunk"],
                "pageOccurrence": c["pageOccurrence"],
                "bulletin": bulletin_label,
                "sourcePdf": os.path.basename(pdf_path),
                "hash": stable_hash(c["chunk"]),
                "charCount": c["charCount"],
                "sourceType": "pdf",
                "program": None,
                "sectionTitle": None,
            }
            raw_rows.append(row)

        summary_rows = build_program_summary_rows(
            pages=pages,
            raw_rows=raw_rows,
            bulletin_label=bulletin_label,
        )
        structured_catalogs.append(
            build_structured_program_catalog(
                summary_rows=summary_rows,
                bulletin_label=bulletin_label,
                source_pdf=os.path.basename(pdf_path),
            )
        )

        # Embed chunks
        texts = [row["chunk"] for row in summary_rows]
        if texts:
            vectors = model.encode(texts, batch_size=16, show_progress_bar=True, normalize_embeddings=True)
        else:
            vectors = np.zeros((0, 384), dtype=np.float32)

        summary_output_rows: List[Dict[str, Any]] = []
        for row, v in zip(summary_rows, vectors):
            chunk_counter += 1
            chunk_id = f"{bulletin_label}:{chunk_counter:06d}"
            summary_row = {
                "chunkId": chunk_id,
                "chunk": row["chunk"],
                "pageOccurrence": row["pageOccurrence"],
                "bulletin": bulletin_label,
                "sourcePdf": os.path.basename(pdf_path),
                "hash": stable_hash(row["chunk"]),
                "charCount": row["charCount"],
                "sourceType": row["sourceType"],
                "program": row["program"],
                "sectionTitle": row["sectionTitle"],
                "sectionType": row.get("sectionType"),
                "sourcePageOccurrence": row.get("sourcePageOccurrence") or [],
                "sourceChunkIds": row.get("sourceChunkIds") or [],
                "programPageOccurrence": row.get("programPageOccurrence") or [],
                "structuredData": row.get("structuredData"),
            }
            summary_output_rows.append(summary_row)
            indexed_rows.append(summary_row)
            indexed_vectors.append(np.array(v, dtype=np.float32))

        all_rows.extend(raw_rows)
        all_rows.extend(summary_output_rows)

        manifest["bulletins"].append({
            "bulletin": bulletin_label,
            "sourcePdf": os.path.basename(pdf_path),
            "pages": doc.page_count,
            "rawChunks": len(raw_rows),
            "programSummaryChunks": len(summary_rows),
            "indexedChunks": len(summary_output_rows),
        })

        doc.close()
        print(
            f"{os.path.basename(pdf_path)} -> pages={len(pages)}, "
            f"raw_chunks={len(raw_rows)}, program_summary_chunks={len(summary_rows)}"
        )

    # Write JSONL
    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(OUT_INDEX_JSONL, "w", encoding="utf-8") as f:
        for r in indexed_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Build FAISS only from structured program-summary chunks.
    if not indexed_vectors:
        raise RuntimeError("No vectors produced. Check header/footer cuts or PDF extraction.")

    mat = np.vstack(indexed_vectors).astype(np.float32)
    dim = mat.shape[1]

    index = faiss.IndexFlatIP(dim)  # cosine-like because we normalized embeddings
    index.add(mat)
    faiss.write_index(index, OUT_FAISS)

    # Manifest
    manifest["totalChunks"] = len(all_rows)
    manifest["totalIndexedChunks"] = len(indexed_rows)
    manifest["faissDim"] = dim
    manifest["faissIndexType"] = "IndexFlatIP (normalized embeddings)"

    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    with open(OUT_PROGRAMS_JSON, "w", encoding="utf-8") as f:
        json.dump(structured_catalogs, f, ensure_ascii=False, indent=2)

    print("\nDONE")
    print(f"JSONL:   {OUT_JSONL}")
    print(f"IndexMeta:{OUT_INDEX_JSONL}")
    print(f"FAISS:   {OUT_FAISS}")
    print(f"Manifest:{OUT_MANIFEST}")
    print(f"Programs:{OUT_PROGRAMS_JSON}")


if __name__ == "__main__":
    ingest_bulletins()
