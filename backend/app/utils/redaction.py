# app/utils/redaction.py
import re

# Add/adjust patterns anytime. Keep them conservative to avoid nuking real content.
_PATTERNS = [
    r"©\s?\d{4}.*",                         # © 2023 Company...
    r"\bcopyright\b.*",                     # copyright lines
    r"\ball rights reserved\b.*",
    r"\bcreative\s+commons\b.*",
    r"\blicense\b.*",
    r"\bterms of use\b.*",
    r"\bnot legal advice\b.*",

    r"\b(confidential|internal use only|do not distribute|for authorized users only)\b.*",

    # Filenames / titles / export headers
    r"^(document|doc(?:ument)?\s*name|file(?:name)?|title)\s*:\s*.*",

    # Page decorations
    r"\bpage\s+\d+\s+of\s+\d+\b",
    r"^\s*-+\s*\d+\s*-+\s*$",

    # URLs & emails
    r"https?://\S+",
    r"\b[\w\.-]+@[\w\.-]+\.\w+\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _PATTERNS]

def redact_source_identity(text: str) -> str:
    """Remove obvious source-identifying lines from text."""
    if not text:
        return ""
    out = text
    for rx in _COMPILED:
        out = rx.sub("", out)
    # Tidy whitespace after removals
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
