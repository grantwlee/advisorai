from urllib.parse import quote


BULLETIN_PDF_ROUTE = "/api/bulletins/pdf"


def _normalize_pdf_pages(row: dict) -> list[int]:
    raw_pages = (
        row.get("sourcePageOccurrence")
        or row.get("pageOccurrence")
        or row.get("programPageOccurrence")
        or []
    )
    pages: list[int] = []
    seen: set[int] = set()
    for value in raw_pages:
        try:
            page = int(value)
        except (TypeError, ValueError):
            continue
        if page <= 0 or page in seen:
            continue
        pages.append(page)
        seen.add(page)
    return pages


def build_pdf_link_metadata(row: dict) -> dict:
    source_pdf = row.get("sourcePdf")
    pdf_pages = _normalize_pdf_pages(row)
    if not source_pdf:
        return {
            "pdfUrl": None,
            "pdfPageUrl": None,
            "pdfPageLinks": [],
        }

    encoded_filename = quote(source_pdf)
    pdf_url = f"{BULLETIN_PDF_ROUTE}/{encoded_filename}"
    pdf_page_links = [
        {
            "page": page,
            "url": f"{pdf_url}#page={page}",
        }
        for page in pdf_pages
    ]
    return {
        "pdfUrl": pdf_url,
        "pdfPageUrl": pdf_page_links[0]["url"] if pdf_page_links else pdf_url,
        "pdfPageLinks": pdf_page_links,
    }


def serialize_chunk_reference(row: dict, *, include_score: bool = False) -> dict:
    payload = {
        "chunkId": row["chunkId"],
        "bulletin": row["bulletin"],
        "pageOccurrence": row.get("pageOccurrence") or [],
        "programPageOccurrence": row.get("programPageOccurrence") or [],
        "sourcePageOccurrence": row.get("sourcePageOccurrence") or [],
        "sourceChunkIds": row.get("sourceChunkIds") or [],
        "preview": row["preview"],
        "chunk": row.get("chunk"),
        "sourcePdf": row.get("sourcePdf"),
        "sourceType": row.get("sourceType"),
        "program": row.get("program"),
        "sectionTitle": row.get("sectionTitle"),
        "sectionType": row.get("sectionType"),
        "structuredData": row.get("structuredData"),
    }
    payload.update(build_pdf_link_metadata(row))
    if include_score:
        payload["score"] = row.get("score")
    return payload
