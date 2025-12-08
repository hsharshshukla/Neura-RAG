# app/routes/admin_bulk_upload.py
from __future__ import annotations

import io
import os
import zipfile
import shutil
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import get_session
from app.deps.auth import get_current_user
from app.models import User  # assumes you already have a User model

# Optional: if you have a Document model + ingestion workers, import them.
# from app.models import Document
# from app.ingestion.pipeline import enqueue_ingestion  # <- if you have a task queue
# Fallback/simple local storage path
STORAGE_DIR = os.getenv("STORAGE_DIR", "storage/uploads")

router = APIRouter(prefix="/api/v1/admin/bulk-upload", tags=["admin:bulk-upload"])

# ---- in-memory job store (swap with db/redis if you prefer) ------------------
_BULK_JOBS: Dict[str, Dict[str, Any]] = {}  # {job_id: {...}}


class BulkUploadInitResponse(BaseModel):
    job_id: str = Field(..., description="Track status with GET /api/v1/admin/bulk-upload/{job_id}")


class BulkUploadStatusFile(BaseModel):
    filename: str
    status: str  # queued | processing | done | error | skipped
    message: Optional[str] = None
    doc_id: Optional[str] = None


class BulkUploadStatusResponse(BaseModel):
    job_id: str
    state: str  # queued | running | done | error
    created_at: str
    meta: Dict[str, Any] = {}
    files: List[BulkUploadStatusFile] = []


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _allowed(filename: str) -> bool:
    # Extend as needed
    allowed_ext = {
        ".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".txt", ".md", ".png", ".jpg", ".jpeg",
    }
    _, ext = os.path.splitext(filename.lower())
    return ext in allowed_ext


def _save_upload_to_disk(f: UploadFile, dest_dir: str) -> str:
    _ensure_dir(dest_dir)
    target = os.path.join(dest_dir, f.filename)
    with open(target, "wb") as out:
        shutil.copyfileobj(f.file, out)
    return target


def _save_bytes_to_disk(filename: str, data: bytes, dest_dir: str) -> str:
    _ensure_dir(dest_dir)
    target = os.path.join(dest_dir, filename)
    with open(target, "wb") as out:
        out.write(data)
    return target


def _register_job(files: List[str], owner_id: str, visibility: str, namespace: Optional[str]) -> str:
    job_id = uuid.uuid4().hex
    _BULK_JOBS[job_id] = {
        "job_id": job_id,
        "state": "queued",
        "created_at": _now_utc_iso(),
        "meta": {
            "owner_id": owner_id,
            "visibility": visibility,  # "private" | "global"
            "namespace": namespace,
        },
        "files": [{"filename": fn, "status": "queued"} for fn in files],
    }
    return job_id


def _update_file_status(job_id: str, idx: int, status: str, message: Optional[str] = None, doc_id: Optional[str] = None):
    rec = _BULK_JOBS[job_id]["files"][idx]
    rec["status"] = status
    if message:
        rec["message"] = message
    if doc_id:
        rec["doc_id"] = doc_id


def _set_job_state(job_id: str, state: str, message: Optional[str] = None):
    _BULK_JOBS[job_id]["state"] = state
    if message:
        _BULK_JOBS[job_id]["meta"]["message"] = message


def _ingest_saved_file(filepath: str, owner_id: str, visibility: str, namespace: Optional[str]) -> Optional[str]:
    """
    Hook your actual ingestion here:
      - OCR / text extraction
      - Create Document row
      - Vector embed + index
    Return a document_id/uuid if created, else None
    """
    # Example stub:
    # doc = Document(
    #     id=uuid.uuid4().hex,
    #     owner_id=owner_id,
    #     path=filepath,
    #     title=os.path.basename(filepath),
    #     visibility=visibility,   # "private" | "global"
    #     namespace=namespace,
    #     created_at=datetime.now(timezone.utc),
    # )
    # session.add(doc); session.commit()
    # enqueue_ingestion(doc.id)
    # return doc.id
    return None


def _process_job(job_id: str, base_dir: str, session: Session, owner: User):
    try:
        _set_job_state(job_id, "running")
        meta = _BULK_JOBS[job_id]["meta"]
        owner_id = meta["owner_id"]
        visibility = meta["visibility"]
        namespace = meta["namespace"]

        for idx, f in enumerate(_BULK_JOBS[job_id]["files"]):
            fname = f["filename"]
            _update_file_status(job_id, idx, "processing")
            fullpath = os.path.join(base_dir, fname)

            # Validate extension
            if not _allowed(fname):
                _update_file_status(job_id, idx, "skipped", "File type not allowed")
                continue

            # TODO: If your ingestion pipeline needs the DB session, pass it inside
            doc_id = _ingest_saved_file(fullpath, owner_id, visibility, namespace)
            _update_file_status(job_id, idx, "done", doc_id=doc_id)

        _set_job_state(job_id, "done")
    except Exception as e:
        _set_job_state(job_id, "error", message=str(e))


@router.post("", response_model=BulkUploadInitResponse)
async def start_bulk_upload(
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
    files: Optional[List[UploadFile]] = File(default=None, description="Multiple files"),
    zip_file: Optional[UploadFile] = File(default=None, description="ZIP containing many files"),
    visibility: str = Form(default="private", description='"private" or "global"'),
    namespace: Optional[str] = Form(default=None, description="Optional logical namespace/tag"),
    owner_id: Optional[str] = Form(default=None, description="Owner user id (defaults to current user, admin can override)"),
):
    """
    Accepts either:
      - multiple files (multipart), or
      - a single zip_file that will be extracted.

    Returns a job_id to poll for status.
    """
    if not files and not zip_file:
        raise HTTPException(status_code=400, detail="Provide either multiple files or a zip_file")

    # Resolve owner (admins may upload on behalf of someone else)
    owner_uid = owner_id or getattr(current, "id", None)
    if not owner_uid:
        raise HTTPException(status_code=400, detail="Cannot resolve owner id")

    tmp_dir = os.path.join(STORAGE_DIR, "bulk", uuid.uuid4().hex)
    _ensure_dir(tmp_dir)

    collected: List[str] = []
    # Handle direct multi-file upload
    if files:
        for f in files:
            if not f.filename:
                continue
            saved = _save_upload_to_disk(f, tmp_dir)
            collected.append(os.path.basename(saved))

    # Handle zip upload
    if zip_file:
        data = await zip_file.read()
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    # Avoid directory traversal
                    bn = os.path.basename(name)
                    if not bn:
                        continue
                    content = zf.read(name)
                    _save_bytes_to_disk(bn, content, tmp_dir)
                    collected.append(bn)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")

    if not collected:
        raise HTTPException(status_code=400, detail="No files found in request")

    job_id = _register_job(collected, str(owner_uid), visibility, namespace)

    # Kick off background processing
    background.add_task(_process_job, job_id, tmp_dir, session, current)

    return BulkUploadInitResponse(job_id=job_id)


@router.get("/{job_id}", response_model=BulkUploadStatusResponse)
def get_bulk_upload_status(job_id: str, user: User = Depends(get_current_user)):
    job = _BULK_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    # (Optional) authz: only admins or owner can view; add your checks here.
    return BulkUploadStatusResponse(**job)
