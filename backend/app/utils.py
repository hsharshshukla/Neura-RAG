import pytesseract
from PIL import Image
import io
import re

def ocr_image(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(img)

def preprocess_text_from_txt(raw_bytes):
    text = raw_bytes.decode('utf-8')
    return clean_text(text)

def clean_text(text):
    text = re.sub(r'(Confidential|©|Page \d+ of \d+|\d{4} Company Name.*?)', '', text, flags=re.I)
    text = re.sub(r'\n+', '\n', text).strip()
    return text
