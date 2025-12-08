# app/parsers/parser.py
from __future__ import annotations

import json
import csv
from io import BytesIO
from typing import Optional, Tuple, Dict
from fastapi import UploadFile, HTTPException

from app.utils.redaction import redact_source_identity
from app.utils.sanitizer import sanitize_text_for_embedding

# Your existing helpers
from app.parsers.txt_parser import preprocess_text_from_txt
from app.parsers.ocr_parser import ocr_image
from app.parsers.pdf_parser import parse_pdf as _pdf_parse  # uses OCR fallback
from app.parsers.docx_parser import parse_docx as _docx_parse

# Optional deps (guarded so missing libs don’t crash uploads)
try:
    from pptx import Presentation  # python-pptx
    from pptx.enum.shapes import MSO_SHAPE_TYPE
except Exception:
    Presentation = None  # type: ignore
    MSO_SHAPE_TYPE = None  # type: ignore

try:
    from openpyxl import load_workbook
except Exception:
    load_workbook = None  # type: ignore

# ---------------------------
# Low-level parsers
# ---------------------------

def _parse_pptx_with_ocr(data: bytes) -> str:
    """
    Extract slide text; OCR any picture shapes if pillow+tesseract available.
    Safe fallback (returns only text) if python-pptx not installed.
    """
    if Presentation is None:
        raise HTTPException(400, "PPTX support not installed (python-pptx)")

    out: list[str] = []
    try:
        prs = Presentation(BytesIO(data))
        for slide in prs.slides:
            # Text from shapes
            for shape in slide.shapes:
                if hasattr(shape, "has_text_frame") and shape.has_text_frame:
                    for p in shape.text_frame.paragraphs:
                        t = "".join(r.text for r in p.runs).strip()
                        if t:
                            out.append(t)

            # OCR from pictures
            for shape in slide.shapes:
                try:
                    if MSO_SHAPE_TYPE and shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                        img = shape.image  # python-pptx Image
                        blob = img.blob  # bytes
                        ocr_text = (ocr_image(blob) or "").strip()
                        if ocr_text:
                            out.append(ocr_text)
                except Exception:
                    # never break entire parse on a single picture
                    pass
    except Exception as e:
        raise HTTPException(400, f"PPTX parse failed: {e}")

    return "\n".join(out).strip()


def _parse_xlsx_with_ocr(data: bytes) -> str:
    """
    Extract cell text; OCR any embedded images if openpyxl available.
    Safe fallback if openpyxl not installed.
    """
    if load_workbook is None:
        raise HTTPException(400, "XLSX support not installed (openpyxl)")

    rows: list[str] = []
    try:
        wb = load_workbook(filename=BytesIO(data), data_only=True)
        for ws in wb.worksheets:
            # text from cells
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                line = "\t".join(cells).strip()
                if line:
                    rows.append(line)

            # best-effort images OCR (openpyxl keeps images on a private attr)
            images = getattr(ws, "_images", []) or getattr(ws, "images", [])
            for img in images:
                try:
                    # openpyxl Image stores PIL.Image or raw stream depending on version
                    pil_img = getattr(img, "_data", None) or getattr(img, "_image", None)
                    if hasattr(pil_img, "fp"):  # PIL Image with file pointer
                        pil_img.fp.seek(0)
                        blob = pil_img.fp.read()
                    elif hasattr(pil_img, "tobytes"):
                        # extremely rare; try to serialize
                        blob = pil_img.tobytes()
                    else:
                        # last resort: many versions store bytes on ._data attribute
                        blob = getattr(img, "_data", None)
                    if blob:
                        ocr_text = (ocr_image(blob) or "").strip()
                        if ocr_text:
                            rows.append(ocr_text)
                except Exception:
                    pass
    except Exception as e:
        raise HTTPException(400, f"XLSX parse failed: {e}")

    return "\n".join(rows).strip()


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


# ---------------------------
# Registry
# ---------------------------

ALLOWED: Dict[str, Tuple[str, str]] = {
    ".pdf":  ("application/pdf", "pdf"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    ".csv":  ("text/csv", "csv"),
    ".json": ("application/json", "json"),
    ".txt":  ("text/plain", "txt"),
    ".md":   ("text/markdown", "txt"),
    ".jpg":  ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".png":  ("image/png", "image"),
}

def _ext(name: str) -> str:
    name = (name or "").lower()
    if "." not in name:
        return ""
    return name[name.rfind("."):]


# ---------------------------
# Public API (used by upload.py)
# ---------------------------

def parse_and_clean_bytes(filename: str, data: bytes, content_type: Optional[str] = None) -> dict:
    """
    Returns {"text": str, "filetype": mime} with safe fallbacks and OCR for images
    (including embedded images in PPTX / XLSX; PDF parser already includes OCR fallback).
    """
    ext = _ext(filename)
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type: {ext or 'unknown'}")

    mime_hint, kind = ALLOWED[ext]

    # ---- text-like
    if kind == "txt":
        try:
            raw = preprocess_text_from_txt(data)
        except Exception:
            raw = data.decode("utf-8", errors="ignore")
        clean = sanitize_text_for_embedding(raw)
        clean = redact_source_identity(clean)
        return {"text": clean, "filetype": mime_hint}

    # ---- images → OCR
    if kind == "image":
        raw = ocr_image(data)
        clean = sanitize_text_for_embedding(raw)
        clean = redact_source_identity(clean)
        return {"text": clean, "filetype": mime_hint}

    # ---- structured types
    if kind == "pdf":
        raw = _pdf_parse(data)  # your parser with OCR fallback via PyMuPDF+pytesseract
    elif kind == "docx":
        # Your docx text parser, PLUS best-effort embedded image OCR
        base = _docx_parse(data)
        try:
            # embedded-image OCR (best-effort, never fatal)
            import docx  # python-docx
            d = docx.Document(BytesIO(data))
            ocr_bits: list[str] = []
            for r_id, part in d.part.related_parts.items():
                try:
                    ctype = getattr(part, "content_type", "") or ""
                    if str(ctype).startswith("image/"):
                        blob = part.blob  # bytes
                        txt = (ocr_image(blob) or "").strip()
                        if txt:
                            ocr_bits.append(txt)
                except Exception:
                    pass
            raw = base if not ocr_bits else (base + "\n" + "\n".join(ocr_bits))
        except Exception:
            raw = base
    elif kind == "pptx":
        raw = _parse_pptx_with_ocr(data)
    elif kind == "xlsx":
        raw = _parse_xlsx_with_ocr(data)
    elif kind == "csv":
        raw = _parse_csv(data)
    elif kind == "json":
        raw = _parse_json(data)
    else:
        raise HTTPException(400, f"No parser implemented for {ext}")

    clean = sanitize_text_for_embedding(raw or "")
    clean = redact_source_identity(clean)
    return {"text": clean, "filetype": mime_hint}


# Back-compat wrapper (if any legacy code passes UploadFile)
def parse_and_clean_file(file: UploadFile) -> dict:
    content = file.file.read()
    return parse_and_clean_bytes(file.filename, content, getattr(file, "content_type", None))


# # app/parsers/parser.py
# import json
# import csv
# from io import BytesIO
# from typing import Optional, Tuple
# from fastapi import UploadFile, HTTPException
# from app.utils.redaction import redact_source_identity
# from app.utils.sanitizer import sanitize_text_for_embedding
# from app.parsers.txt_parser import preprocess_text_from_txt
# from app.parsers.ocr_parser import ocr_image
# # from app.utils.text import preprocess_text_from_txt, ocr_image  # keep your helpers

# # Optional parsers (import errors become helpful HTTP 400s)
# def _parse_pdf(data: bytes) -> str:
#     try:
#         from pypdf import PdfReader
#     except Exception as e:
#         raise HTTPException(400, f"PDF support not installed: {e}")
#     try:
#         reader = PdfReader(BytesIO(data))
#         pages = []
#         for p in reader.pages:
#             pages.append(p.extract_text() or "")
#         return "\n".join(pages).strip()
#     except Exception as e:
#         raise HTTPException(400, f"PDF parse failed: {e}")

# def _parse_docx(data: bytes) -> str:
#     try:
#         import docx
#     except Exception as e:
#         raise HTTPException(400, f"DOCX support not installed: {e}")
#     try:
#         d = docx.Document(BytesIO(data))
#         return "\n".join([p.text for p in d.paragraphs]).strip()
#     except Exception as e:
#         raise HTTPException(400, f"DOCX parse failed: {e}")

# def _parse_pptx(data: bytes) -> str:
#     try:
#         from pptx import Presentation
#     except Exception as e:
#         raise HTTPException(400, f"PPTX support not installed: {e}")
#     try:
#         prs = Presentation(BytesIO(data))
#         out = []
#         for slide in prs.slides:
#             for shape in slide.shapes:
#                 if hasattr(shape, "text"):
#                     out.append(shape.text)
#         return "\n".join(out).strip()
#     except Exception as e:
#         raise HTTPException(400, f"PPTX parse failed: {e}")

# def _parse_xlsx(data: bytes) -> str:
#     try:
#         from openpyxl import load_workbook
#     except Exception as e:
#         raise HTTPException(400, f"XLSX support not installed: {e}")
#     try:
#         wb = load_workbook(filename=BytesIO(data), data_only=True)
#         rows = []
#         for ws in wb.worksheets:
#             for row in ws.iter_rows(values_only=True):
#                 cells = ["" if c is None else str(c) for c in row]
#                 rows.append("\t".join(cells))
#         return "\n".join(rows).strip()
#     except Exception as e:
#         raise HTTPException(400, f"XLSX parse failed: {e}")

# def _parse_csv(data: bytes) -> str:
#     try:
#         text = data.decode("utf-8", errors="ignore")
#     except Exception:
#         text = data.decode("latin-1", errors="ignore")
#     try:
#         reader = csv.reader(text.splitlines())
#         rows = ["\t".join(row) for row in reader]
#         return "\n".join(rows).strip()
#     except Exception as e:
#         raise HTTPException(400, f"CSV parse failed: {e}")

# def _parse_json(data: bytes) -> str:
#     try:
#         obj = json.loads(data.decode("utf-8", errors="ignore"))
#         return json.dumps(obj, indent=2, ensure_ascii=False)
#     except Exception as e:
#         raise HTTPException(400, f"JSON parse failed: {e}")

# ALLOWED = {
#     ".pdf": ("application/pdf", _parse_pdf),
#     ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", _parse_docx),
#     ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", _parse_pptx),
#     ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _parse_xlsx),
#     ".csv": ("text/csv", _parse_csv),
#     ".json": ("application/json", _parse_json),
#     ".txt": ("text/plain", None),   # handled via preprocess_text_from_txt
#     ".md":  ("text/markdown", None),# treat as text
#     ".jpg": ("image/jpeg", None),   # OCR
#     ".jpeg":("image/jpeg", None),
#     ".png": ("image/png", None),
# }

# def _ext(name: str) -> str:
#     name = (name or "").lower()
#     if "." not in name: return ""
#     return name[name.rfind("."):]

# def parse_and_clean_bytes(filename: str, data: bytes, content_type: Optional[str] = None) -> dict:
#     ext = _ext(filename)
#     if ext not in ALLOWED:
#         raise HTTPException(400, f"Unsupported file type: {ext or 'unknown'}")

#     mime_hint, parser = ALLOWED[ext]

#     # text-like
#     if ext in (".txt", ".md"):
#         try:
#             raw = preprocess_text_from_txt(data)
#         except Exception:
#             raw = data.decode("utf-8", errors="ignore")
#         clean = sanitize_text_for_embedding(raw)
#         clean = redact_source_identity(clean)
#         return {"text": clean, "filetype": mime_hint}

#     # images → OCR (your existing helper)
#     if ext in (".jpg", ".jpeg", ".png"):
#         raw = ocr_image(data)
#         clean = sanitize_text_for_embedding(raw)
#         clean = redact_source_identity(clean)
#         return {"text": clean, "filetype": mime_hint}

#     # structured via parser
#     if parser is None:
#         raise HTTPException(400, f"No parser implemented for {ext}")
#     raw = parser(data)

#     clean = sanitize_text_for_embedding(raw)
#     clean = redact_source_identity(clean)
#     return {"text": clean, "filetype": mime_hint}

# # Back-compat wrapper (if some code still calls with UploadFile)
# def parse_and_clean_file(file: UploadFile) -> dict:
#     content = file.file.read()
#     return parse_and_clean_bytes(file.filename, content, getattr(file, "content_type", None))
