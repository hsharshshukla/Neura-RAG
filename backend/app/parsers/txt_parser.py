# app/parsers/txt_parser.py
from __future__ import annotations
import re

def preprocess_text_from_txt(data: bytes) -> str:
    """
    Decode raw bytes from .txt/.md safely and normalize for embedding.
    - tolerates unknown encodings
    - normalizes newlines
    - strips NULs and excessive blank lines
    """
    if data is None:
        return ""

    # Best-effort decode
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        text = data.decode("latin-1", errors="ignore")

    # Remove UTF-8 BOM if present
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")

    # Normalize newlines and strip NULs
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")

    # Collapse excessive blank lines (keep at most 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Trim trailing spaces on each line
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    # Optional: cap overly long repeating whitespace
    text = re.sub(r"[ \t]{4,}", "   ", text)

    return text.strip()
