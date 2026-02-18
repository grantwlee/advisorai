from bs4 import BeautifulSoup
from dataclasses import dataclass
import re


@dataclass
class HtmlSection:
    heading: str
    text: str


def _clean_text(text: str) -> str:
    # collapse repeated spaces/tabs
    text = re.sub(r"[ \t]+", " ", text)
    # collapse 3+ newlines into double newline
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_html_sections(html_path: str) -> list[HtmlSection]:
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    # remove junk elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    sections: list[HtmlSection] = []
    current_heading = "Untitled"
    buffer: list[str] = []

    for el in soup.find_all(["h1", "h2", "h3", "p", "li"]):

        # If it's a heading, flush previous section
        if el.name in ("h1", "h2", "h3"):
            if buffer:
                sections.append(
                    HtmlSection(
                        current_heading,
                        _clean_text("\n".join(buffer))
                    )
                )
                buffer = []

            current_heading = _clean_text(
                el.get_text(" ", strip=True)
            ) or "Untitled"

        else:
            text = _clean_text(el.get_text(" ", strip=True))
            if text:
                buffer.append(text)

    # Flush last section
    if buffer:
        sections.append(
            HtmlSection(
                current_heading,
                _clean_text("\n".join(buffer))
            )
        )

    # Drop tiny garbage sections
    sections = [s for s in sections if len(s.text) >= 200]

    return sections