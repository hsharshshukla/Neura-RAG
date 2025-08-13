# app/parsers/ocr.py
from __future__ import annotations
import io

try:
    from PIL import Image  # pip install pillow
except Exception:
    Image = None  # type: ignore

try:
    import pytesseract  # pip install pytesseract (requires Tesseract binary installed)
except Exception:
    pytesseract = None  # type: ignore


def ocr_image(data: bytes) -> str:
    """
    Best-effort OCR that never crashes:
    - If Pillow/Tesseract not available, return a safe stub so uploads don't fail.
    - If image unreadable or OCR empty, return a stub.
    """
    if Image is None:
        return "Image content (OCR not available)."

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))  # reopen after verify
    except Exception:
        return "Image content (unreadable or unsupported image)."

    if pytesseract is None:
        return "Image content (OCR engine not installed)."

    try:
        text = (pytesseract.image_to_string(img) or "").strip()
    except Exception:
        return "Image content (OCR failed)."

    return text if text else "Image content (no OCR text found)."
