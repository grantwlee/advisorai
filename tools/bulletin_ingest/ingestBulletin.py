import os
import re
import json
import hashlib
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple

import fitz  # PyMuPDF
import numpy as np
import faiss

from sentence_transformers import SentenceTransformer


# ----------------------------
# Config
# ----------------------------
RAW_DIR = "data/bulletins/raw"
OUT_DIR = "data/bulletins/processed"

OUT_JSONL = os.path.join(OUT_DIR, "bulletin_chunks.jsonl")
OUT_MANIFEST = os.path.join(OUT_DIR, "bulletin_chunks_manifest.json")
OUT_FAISS = os.path.join(OUT_DIR, "bulletin_index.faiss")

# Header/footer removal:
# remove anything in the top X% and bottom Y% of a page
HEADER_CUT = 0.08   # top 8% of page height
FOOTER_CUT = 0.08   # bottom 8% of page height

# Chunking
TARGET_WORDS = 500
MAX_WORDS = 800
MIN_WORDS = 80

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
    kept: List[Tuple[float, str]] = []

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

        # Keep in reading order (y then x)
        kept.append((y0, t))

    kept.sort(key=lambda x: x[0])
    combined = "\n".join([t for _, t in kept])
    return normalize_whitespace(combined)


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

    # Sentence-aware, word-count-based chunking
    sentence_pattern = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
    sentence_matches = list(sentence_pattern.finditer(doc_text))

    chunks = []
    current_sentences: List[str] = []
    current_pages: set[int] = set()
    current_word_count = 0

    def flush_current():
        nonlocal current_sentences, current_pages, current_word_count
        if current_word_count < MIN_WORDS:
            return
        chunk_text = normalize_whitespace(" ".join(current_sentences))
        if not chunk_text:
            return
        chunks.append({
            "chunk": chunk_text,
            "pageOccurrence": sorted(current_pages),
            "charCount": len(chunk_text),
        })
        current_sentences = []
        current_pages = set()
        current_word_count = 0

    for m in sentence_matches:
        sentence = m.group(0).strip()
        if not sentence:
            continue

        sentence_words = sentence.split()
        sentence_word_count = len(sentence_words)
        s_start, s_end = m.span()

        sentence_pages = set()
        for start, end, pg in spans:
            if s_end <= start or s_start >= end:
                continue
            sentence_pages.add(pg)

        # If adding this sentence would exceed max, flush first.
        if current_sentences and (current_word_count + sentence_word_count > MAX_WORDS):
            flush_current()

        current_sentences.append(sentence)
        current_pages.update(sentence_pages)
        current_word_count += sentence_word_count

        # Flush once target is reached to keep chunk sizes around ~500 words.
        if current_word_count >= TARGET_WORDS:
            flush_current()

    # Flush tail
    flush_current()

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
    all_vectors: List[np.ndarray] = []

    chunk_counter = 0
    manifest = {
        "sourceDir": RAW_DIR,
        "outDir": OUT_DIR,
        "model": MODEL_NAME,
        "headerCutPct": HEADER_CUT,
        "footerCutPct": FOOTER_CUT,
        "targetWords": TARGET_WORDS,
        "maxWords": MAX_WORDS,
        "minWords": MIN_WORDS,
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

        # Embed chunks
        texts = [c["chunk"] for c in chunks]
        if texts:
            vectors = model.encode(texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True)
        else:
            vectors = np.zeros((0, 384), dtype=np.float32)

        for c, v in zip(chunks, vectors):
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
            }
            all_rows.append(row)
            all_vectors.append(np.array(v, dtype=np.float32))

        manifest["bulletins"].append({
            "bulletin": bulletin_label,
            "sourcePdf": os.path.basename(pdf_path),
            "pages": doc.page_count,
            "chunks": len(chunks),
        })

        doc.close()
        print(f"{os.path.basename(pdf_path)} -> pages={len(pages)}, chunks={len(chunks)}")

    # Write JSONL
    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Build FAISS.   
    if not all_vectors:
        raise RuntimeError("No vectors produced. Check header/footer cuts or PDF extraction.")

    mat = np.vstack(all_vectors).astype(np.float32)
    dim = mat.shape[1]

    index = faiss.IndexFlatIP(dim)  # cosine-like because we normalized embeddings
    index.add(mat)
    faiss.write_index(index, OUT_FAISS)

    # Manifest
    manifest["totalChunks"] = len(all_rows)
    manifest["faissDim"] = dim
    manifest["faissIndexType"] = "IndexFlatIP (normalized embeddings)"

    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\nDONE")
    print(f"JSONL:   {OUT_JSONL}")
    print(f"FAISS:   {OUT_FAISS}")
    print(f"Manifest:{OUT_MANIFEST}")


if __name__ == "__main__":
    ingest_bulletins()
