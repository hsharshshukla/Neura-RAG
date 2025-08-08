import re

COMMON_CORPORATE_TAGS = [
    "confidential", "internal use only", "do not distribute",
    "for authorized users only", "company confidential",
    "examplecorp", "neura ai", "google", "microsoft", "ibm"
]

def sanitize_text_for_embedding(text: str) -> str:
    lines = text.split("\n")
    clean_lines = []
    seen_headers = set()

    for line in lines:
        original = line
        line = line.strip()

        if not line:
            continue

        # Common copyright/license/disclaimer patterns
        if re.search(r"(copyright|\©|all rights reserved)", line, re.IGNORECASE):
            continue
        if re.search(r"(creative commons|license|terms of use|not legal advice)", line, re.IGNORECASE):
            continue
        if re.search(r"(published by|press|publication date)", line, re.IGNORECASE):
            continue
        if re.search(r"(confidential|internal use only|do not distribute|for authorized users only)", line, re.IGNORECASE):
            continue

        # Remove common company tags and corporate names
        if any(tag in line.lower() for tag in COMMON_CORPORATE_TAGS):
            continue

        # Page numbers or standalone dates
        if re.match(r"^(page\s+\d+|\d+\s*/\s*\d+|\-+\s*\d+\s*\-+)$", line, re.IGNORECASE):
            continue
        if re.match(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$", line):  # e.g., August 7, 2025
            continue

        # Repeated headers/footers (naive de-duplication)
        if line in seen_headers:
            continue
        seen_headers.add(line)

        clean_lines.append(original)

    return "\n".join(clean_lines)
