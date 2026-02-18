import json
import argparse

from ingest.loaders.pdf_loader import load_pdf_pages
from ingest.loaders.html_loader import load_html_sections
from ingest.chunking.chunker import split_into_chunks, infer_program, make_hash
from ingest.db.pg_writer import get_conn, insert_chunk


def ingest_pdf(item: dict):
    pages = load_pdf_pages(item["path"])

    conn = get_conn()
    cur = conn.cursor()

    inserted = 0
    skipped = 0

    for p in pages:
        section_title = "PDF Page Content"  # Week 5 rule-based placeholder
        program = infer_program(p.text)
        pieces = split_into_chunks(p.text)

        for idx, chunk_text in enumerate(pieces):
            ch = make_hash(
                item["bulletin_id"],
                item["bulletin_year"],
                str(p.page_number),
                str(idx),
                chunk_text[:500],
            )

            row = (
                item["bulletin_id"],
                "pdf",
                item["bulletin_year"],
                program,
                section_title,
                p.page_number,
                idx,
                ch,
                chunk_text,
            )

            if insert_chunk(cur, row):
                inserted += 1
            else:
                skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    print(
        f"[PDF] {item['bulletin_id']} "
        f"pages={len(pages)} inserted={inserted} skipped={skipped}"
    )


def ingest_html(item: dict):
    sections = load_html_sections(item["path"])

    conn = get_conn()
    cur = conn.cursor()

    inserted = 0
    skipped = 0

    for s in sections:
        program = infer_program(s.text)
        pieces = split_into_chunks(s.text)

        for idx, chunk_text in enumerate(pieces):
            ch = make_hash(
                item["bulletin_id"],
                item["bulletin_year"],
                s.heading,
                str(idx),
                chunk_text[:500],
            )

            row = (
                item["bulletin_id"],
                "html",
                item["bulletin_year"],
                program,
                s.heading,
                None,
                idx,
                ch,
                chunk_text,
            )

            if insert_chunk(cur, row):
                inserted += 1
            else:
                skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    print(
        f"[HTML] {item['bulletin_id']} "
        f"sections={len(sections)} inserted={inserted} skipped={skipped}"
    )


def run(manifest_path: str):
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    for item in manifest["bulletins"]:
        if item["type"] == "pdf":
            ingest_pdf(item)
        elif item["type"] == "html":
            ingest_html(item)
        else:
            print("Unknown type:", item["type"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args()

    run(args.manifest)