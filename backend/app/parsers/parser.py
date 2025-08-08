import os
from fastapi import UploadFile, HTTPException
from app.utils.sanitizer import sanitize_text_for_embedding
from app.utils import preprocess_text_from_txt, ocr_image

# Optional imports (if PDF/DOCX supported)
from app.parsers.pdf_parser import parse_pdf
from app.parsers.docx_parser import parse_docx

def parse_and_clean_file(file: UploadFile) -> dict:
    filename = file.filename.lower()
    content = file.file.read()

    # TXT
    if filename.endswith(".txt"):
        raw_text = preprocess_text_from_txt(content)
        filetype = "text/plain"

    # IMAGE (OCR)
    elif filename.endswith((".jpg", ".jpeg", ".png")):
        raw_text = ocr_image(content)
        filetype = "image/jpeg"

    # PDF (placeholder)
    elif filename.endswith(".pdf"):
        raw_text = parse_pdf(content)
        filetype = "application/pdf"

    # DOCX (placeholder)
    elif filename.endswith(".docx"):
        raw_text = parse_docx(content)
        filetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # Sanitize for embedding
    clean_text = sanitize_text_for_embedding(raw_text)

    return {
        "text": clean_text,
        "filetype": filetype
    }
