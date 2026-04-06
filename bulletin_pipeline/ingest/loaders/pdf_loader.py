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


def _order_text_blocks_for_reading(
    blocks: list[tuple[float, float, float, float, str]],
    page_width: float,
) -> list[tuple[float, float, float, float, str]]:
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

    leading_full: list[tuple[float, float, float, float, str]] = []
    trailing_full: list[tuple[float, float, float, float, str]] = []
    left_column: list[tuple[float, float, float, float, str]] = []
    right_column: list[tuple[float, float, float, float, str]] = []

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

def load_pdf_pages(pdf_path: str) -> list[PdfPage]:
    doc = fitz.open(pdf_path)
    pages: list[PdfPage] = []
    for i in range(doc.page_count):
        page = doc.load_page(i)
        blocks = page.get_text("blocks")
        kept = [
            (x0, y0, x1, y1, text.strip())
            for x0, y0, x1, y1, text, *_ in blocks
            if text and text.strip()
        ]
        ordered = _order_text_blocks_for_reading(kept, page.rect.width)
        raw = "\n".join(text for *_coords, text in ordered)
        cleaned = _clean_page_text(raw)
        pages.append(PdfPage(page_number=i + 1, text=cleaned))
    return pages
