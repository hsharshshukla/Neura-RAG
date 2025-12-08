# app/compression/compressors.py
from __future__ import annotations

import io
import os
import zipfile
from typing import Tuple

# Optional libs (gracefully degrade)
try:
    from PIL import Image  # pillow
except Exception:
    Image = None  # type: ignore

try:
    import pikepdf  # pure-python PDF optimizer
except Exception:
    pikepdf = None  # type: ignore


OOXML_EXTS = {".docx", ".pptx", ".xlsx"}  # ZIP containers
PNG_EXTS = {".png"}
PDF_EXTS = {".pdf"}
JPEG_EXTS = {".jpg", ".jpeg"}


def _ext(name: str) -> str:
    name = (name or "").lower()
    if "." not in name:
        return ""
    return name[name.rfind(".") :]


def _repack_ooxml_zip_lossless(data: bytes) -> bytes:
    """
    Repack OOXML (docx/pptx/xlsx) with DEFLATED level 9.
    Does not modify entry data; fully lossless.
    """
    src = io.BytesIO(data)
    dst = io.BytesIO()

    with zipfile.ZipFile(src, "r") as zin:
        with zipfile.ZipFile(
            dst,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as zout:
            for info in zin.infolist():
                # read the original bytes of each entry
                buf = zin.read(info.filename)
                # Preserve filename; timestamps may differ but content stays intact
                zi = zipfile.ZipInfo(filename=info.filename)
                # Set a sane timestamp (avoid localtime skew in zips)
                zi.date_time = (1980, 1, 1, 0, 0, 0)
                zi.external_attr = info.external_attr
                zi.create_system = info.create_system
                zi.flag_bits = info.flag_bits & ~0x08  # clear "data descriptor present" bit
                zout.writestr(zi, buf)
    return dst.getvalue()


def _optimize_png_lossless(data: bytes) -> bytes:
    """
    Re-encode PNG with Pillow optimize=True (lossless).
    If Pillow unavailable or fails, return original.
    """
    if Image is None:
        return data
    try:
        im = Image.open(io.BytesIO(data))
        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return data


def _optimize_pdf_lossless(data: bytes) -> bytes:
    """
    Use pikepdf to rewrite object streams / deflate streams.
    Avoids image re-encoding (so 'lossless' in structure).
    If pikepdf unavailable or error, return original.
    """
    if pikepdf is None:
        return data
    try:
        src = io.BytesIO(data)
        dst = io.BytesIO()
        with pikepdf.open(src) as pdf:
            # Keep content intact; optimize streams
            pdf.save(
                dst,
                # object streams & xref streams help reduce size; do not recompress images explicitly
                # (pikepdf may deflate streams that are flate-compressible)
                # Use default settings which are safe.
                linearize=False,
                # preserve_pdfa=True would keep conformance if present (optional)
            )
        new_data = dst.getvalue()
        # Only accept if smaller (avoid “growing” PDFs)
        return new_data if len(new_data) < len(data) else data
    except Exception:
        return data


def _optimize_jpeg_lossless(data: bytes) -> bytes:
    """
    True JPEG lossless optimization typically needs jpegtran/mozjpeg (external).
    To stay pure-Python and risk-free, we return original bytes.
    """
    return data


def compress_bytes(filename: str, data: bytes, mime: str | None = None) -> Tuple[bytes, str, bool, str]:
    """
    Returns (compressed_bytes, mime_out, changed, note)

    - Changed = True only if size decreased and we’re confident it’s lossless.
    - We never modify content for unknown types.
    - JPEG left untouched (pure-Python, risk of re-encoding).
    """
    ext = _ext(filename)

    # Default passthrough
    out = data
    note = "pass"
    changed = False
    mime_out = mime or ""

    if ext in OOXML_EXTS:
        try:
            repacked = _repack_ooxml_zip_lossless(data)
            if len(repacked) < len(data):
                out = repacked
                changed = True
                note = "ooxml_zip_deflated"
        except Exception:
            pass

    elif ext in PNG_EXTS:
        comp = _optimize_png_lossless(data)
        if len(comp) < len(data):
            out = comp
            changed = True
            note = "png_optimize"

    elif ext in PDF_EXTS:
        comp = _optimize_pdf_lossless(data)
        if len(comp) < len(data):
            out = comp
            changed = True
            note = "pdf_optimize"

    elif ext in JPEG_EXTS:
        # Keep as-is (lossless tools not available by default)
        note = "jpeg_passthrough"

    else:
        # txt/csv/json: optionally gzip if env flag is set
        # We avoid changing stored MIME/extension by default.
        if os.getenv("COMPRESS_TEXT_GZIP", "").lower() in ("1", "true", "yes"):
            import gzip
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
                gz.write(data)
            gz_bytes = buf.getvalue()
            if len(gz_bytes) < len(data):
                out = gz_bytes
                changed = True
                note = "gzip_text"
                # if you prefer to keep mime the same, do nothing;
                # otherwise you could set: mime_out = "application/gzip"

    return out, mime_out, changed, note
