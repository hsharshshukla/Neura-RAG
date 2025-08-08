import io
from typing import Optional
from PyPDF2 import PdfReader
from PIL import Image
import fitz  # PyMuPDF
import pytesseract
import tempfile

def parse_pdf(file_bytes: bytes) -> str:
    full_text = ""

    try:
        # First try with PyPDF2
        reader = PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                full_text += extracted + "\n"
    except Exception as e:
        print(f"[PyPDF2 ERROR]: {e}")

    # If text is too short, try OCR fallback
    if len(full_text.strip()) < 50:
        print("[INFO] Fallback to OCR for PDF")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                pdf = fitz.open(stream=file_bytes, filetype="pdf")
                for page_number in range(len(pdf)):
                    page = pdf[page_number]
                    pix = page.get_pixmap(dpi=300)
                    image_path = f"{temp_dir}/page_{page_number}.png"
                    pix.save(image_path)

                    text = pytesseract.image_to_string(Image.open(image_path))
                    full_text += text + "\n"
        except Exception as e:
            print(f"[OCR FALLBACK ERROR]: {e}")

    return full_text.strip()
