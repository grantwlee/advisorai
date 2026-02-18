from dataclasses import dataclass
import re
import fitz # pymupdf

@dataclass
class PdfPage:
    page_number: int
    text: str

def _clean_page_text(text: str) -> str:
    # normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def load_pdf_pages(pdf_path: str) -> list[PdfPage]:
    doc = fitz.open(pdf_path)
    pages: list[PdfPage] = []
    for i in range(doc.page_count):
        page = doc.load_page(i)
        raw = page.get_text("text") or ""
        cleaned = _clean_page_text(raw)
        pages.append(PdfPage(page_number=i + 1, text=cleaned))
    return pages