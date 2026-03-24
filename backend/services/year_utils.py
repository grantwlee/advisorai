import re


def normalize_bulletin_year(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if re.fullmatch(r"\d{2}-\d{2}", cleaned):
        return cleaned
    match = re.fullmatch(r"(\d{4})-(\d{4})", cleaned)
    if match:
        return f"{match.group(1)[2:]}-{match.group(2)[2:]}"
    return cleaned


def expand_bulletin_year(value: str | None) -> str | None:
    short = normalize_bulletin_year(value)
    if not short or not re.fullmatch(r"\d{2}-\d{2}", short):
        return value
    start, end = short.split("-")
    return f"20{start}-20{end}"
