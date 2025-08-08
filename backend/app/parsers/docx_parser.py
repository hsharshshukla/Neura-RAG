from docx import Document
from typing import List
import io

def parse_docx(file_bytes: bytes) -> str:
    try:
        doc = Document(io.BytesIO(file_bytes))
        paragraphs: List[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        return "\n".join(paragraphs)
    except Exception as e:
        print(f"[DOCX PARSER ERROR]: {e}")
        return ""
