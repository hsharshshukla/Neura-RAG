# app/parsers/parser.py
import json
import csv
from io import BytesIO
from typing import Optional, Tuple
from fastapi import UploadFile, HTTPException
from app.utils.redaction import redact_source_identity
from app.utils.sanitizer import sanitize_text_for_embedding
from app.utils.text import preprocess_text_from_txt, ocr_image  # keep your helpers

# Optional parsers (import errors become helpful HTTP 400s)
def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception as e:
        raise HTTPException(400, f"PDF support not installed: {e}")
    try:
        reader = PdfReader(BytesIO(data))
        pages = []
        for p in reader.pages:
            pages.append(p.extract_text() or "")
        return "\n".join(pages).strip()
    except Exception as e:
        raise HTTPException(400, f"PDF parse failed: {e}")

def _parse_docx(data: bytes) -> str:
    try:
        import docx
    except Exception as e:
        raise HTTPException(400, f"DOCX support not installed: {e}")
    try:
        d = docx.Document(BytesIO(data))
        return "\n".join([p.text for p in d.paragraphs]).strip()
    except Exception as e:
        raise HTTPException(400, f"DOCX parse failed: {e}")

def _parse_pptx(data: bytes) -> str:
    try:
        from pptx import Presentation
    except Exception as e:
        raise HTTPException(400, f"PPTX support not installed: {e}")
    try:
        prs = Presentation(BytesIO(data))
        out = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    out.append(shape.text)
        return "\n".join(out).strip()
    except Exception as e:
        raise HTTPException(400, f"PPTX parse failed: {e}")

def _parse_xlsx(data: bytes) -> str:
    try:
        from openpyxl import load_workbook
    except Exception as e:
        raise HTTPException(400, f"XLSX support not installed: {e}")
    try:
        wb = load_workbook(filename=BytesIO(data), data_only=True)
        rows = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                rows.append("\t".join(cells))
        return "\n".join(rows).strip()
    except Exception as e:
        raise HTTPException(400, f"XLSX parse failed: {e}")

def _parse_csv(data: bytes) -> str:
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        text = data.decode("latin-1", errors="ignore")
    try:
        reader = csv.reader(text.splitlines())
        rows = ["\t".join(row) for row in reader]
        return "\n".join(rows).strip()
    except Exception as e:
        raise HTTPException(400, f"CSV parse failed: {e}")

def _parse_json(data: bytes) -> str:
    try:
        obj = json.loads(data.decode("utf-8", errors="ignore"))
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception as e:
        raise HTTPException(400, f"JSON parse failed: {e}")

ALLOWED = {
    ".pdf": ("application/pdf", _parse_pdf),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", _parse_docx),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", _parse_pptx),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _parse_xlsx),
    ".csv": ("text/csv", _parse_csv),
    ".json": ("application/json", _parse_json),
    ".txt": ("text/plain", None),   # handled via preprocess_text_from_txt
    ".md":  ("text/markdown", None),# treat as text
    ".jpg": ("image/jpeg", None),   # OCR
    ".jpeg":("image/jpeg", None),
    ".png": ("image/png", None),
}

def _ext(name: str) -> str:
    name = (name or "").lower()
    if "." not in name: return ""
    return name[name.rfind("."):]

def parse_and_clean_bytes(filename: str, data: bytes, content_type: Optional[str] = None) -> dict:
    ext = _ext(filename)
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type: {ext or 'unknown'}")

    mime_hint, parser = ALLOWED[ext]

    # text-like
    if ext in (".txt", ".md"):
        try:
            raw = preprocess_text_from_txt(data)
        except Exception:
            raw = data.decode("utf-8", errors="ignore")
        clean = sanitize_text_for_embedding(raw)
        clean = redact_source_identity(clean)
        return {"text": clean, "filetype": mime_hint}

    # images → OCR (your existing helper)
    if ext in (".jpg", ".jpeg", ".png"):
        raw = ocr_image(data)
        clean = sanitize_text_for_embedding(raw)
        clean = redact_source_identity(clean)
        return {"text": clean, "filetype": mime_hint}

    # structured via parser
    if parser is None:
        raise HTTPException(400, f"No parser implemented for {ext}")
    raw = parser(data)

    clean = sanitize_text_for_embedding(raw)
    clean = redact_source_identity(clean)
    return {"text": clean, "filetype": mime_hint}

# Back-compat wrapper (if some code still calls with UploadFile)
def parse_and_clean_file(file: UploadFile) -> dict:
    content = file.file.read()
    return parse_and_clean_bytes(file.filename, content, getattr(file, "content_type", None))
