from __future__ import annotations

from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.db import get_session
from app.deps.workspace import WorkspaceAccess, require_tkp_workspace_access
from app.integrations.tkp.client import TKPClientError, TKPIngestionClient
from app.models import TKPBulkUploadDocument, TKPBulkUploadJob

router = APIRouter(prefix="/api/v1/admin/bulk-upload", tags=["admin:bulk-upload"])


class RetryDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_ids: tuple[str, ...] = Field(min_length=1, max_length=100)


def _client(request: Request) -> TKPIngestionClient:
    client = getattr(request.app.state, "tkp_ingestion_client", None)
    if not isinstance(client, TKPIngestionClient):
        raise HTTPException(status_code=503, detail="Knowledge ingestion is not configured")
    return client


def _correlation_id(request: Request) -> UUID:
    try:
        return UUID(str(request.state.correlation_id))
    except (AttributeError, TypeError, ValueError):
        return uuid4()


def _require_write(access: WorkspaceAccess) -> None:
    if access.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Knowledge workspace write denied")


def _error_response(error: TKPClientError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "message": error.public_message,
            "correlation_id": str(error.correlation_id),
            "details": None,
        },
    )


def _job(job_id: str, access: WorkspaceAccess, db: Session) -> TKPBulkUploadJob:
    value = db.exec(
        select(TKPBulkUploadJob).where(
            TKPBulkUploadJob.id == job_id,
            TKPBulkUploadJob.workspace_id == str(access.workspace_id),
            TKPBulkUploadJob.owner_user_id == access.user.id,
        )
    ).first()
    if value is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return value


def _documents(job_id: str, access: WorkspaceAccess, db: Session) -> list[TKPBulkUploadDocument]:
    return list(
        db.exec(
            select(TKPBulkUploadDocument).where(
                TKPBulkUploadDocument.bulk_job_id == job_id,
                TKPBulkUploadDocument.workspace_id == str(access.workspace_id),
                TKPBulkUploadDocument.owner_user_id == access.user.id,
            )
        ).all()
    )


def _document_from_job(body: dict[str, Any]) -> dict[str, Any]:
    job = body.get("job")
    return job if isinstance(job, dict) else {}


def _aggregate(
    bulk_job: TKPBulkUploadJob,
    documents: list[TKPBulkUploadDocument],
) -> dict[str, Any]:
    processing_values = [document.processing_status for document in documents]
    processing_complete = bool(documents) and all(
        value in {"COMPLETED", "FAILED"} for value in processing_values
    )
    index_values = [document.index_status for document in documents]
    search_ready = bool(documents) and all(value == "READY" for value in index_values)

    return {
        "job_id": bulk_job.id,
        "workspace_id": bulk_job.workspace_id,
        "processing_complete": processing_complete,
        "search_index_ready": search_ready,
        "documents": [
            {
                "document_id": document.id,
                "filename": document.filename,
                "tkp_job_id": document.tkp_job_id,
                "status": document.processing_status,
                "processing_status": document.processing_status,
                "index_status": document.index_status,
                "retryable": document.retryable,
                "error_code": document.error_code,
                "error": document.error_message,
                "sanitized_error": document.error_message,
                "source_version_id": document.source_version_id,
                "revision_id": document.revision_id,
            }
            for document in documents
        ],
    }


@router.get("/limits", response_model=None)
async def bulk_upload_limits(
    request: Request,
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
) -> dict[str, Any] | JSONResponse:
    _require_write(access)
    correlation_id = _correlation_id(request)
    try:
        return await _client(request).limits(correlation_id)
    except TKPClientError as error:
        return _error_response(error)


@router.post("", response_model=None)
async def start_bulk_upload(
    request: Request,
    files: list[UploadFile] = File(..., min_length=1),
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
    db: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    _require_write(access)
    correlation_id = _correlation_id(request)
    client = _client(request)
    limits = await client.limits(correlation_id)
    source = limits.get("limits", limits)

    max_files = int(source.get("max_files") or len(files))
    max_file = int(source.get("max_file_size_bytes") or 0)
    max_total = int(source.get("max_total_size_bytes") or 0)
    allowed = {
        str(value).lower().lstrip(".")
        for value in source.get("allowed_extensions", ())
    }
    if len(files) > max_files:
        raise HTTPException(status_code=413, detail="Upload contains too many documents")

    total = 0
    for upload in files:
        filename = PurePath((upload.filename or "").replace("\\", "/")).name
        if not filename or filename in {".", ".."}:
            raise HTTPException(status_code=400, detail="Every upload requires a filename")
        upload.file.seek(0, 2)
        size = upload.file.tell()
        upload.file.seek(0)
        total += size
        if max_file and size > max_file:
            raise HTTPException(status_code=413, detail="A document exceeds the file size limit")
        if allowed:
            extension = PurePath(filename).suffix.lower().lstrip(".")
            if extension not in allowed:
                raise HTTPException(status_code=415, detail="A document type is not allowed")
    if max_total and total > max_total:
        raise HTTPException(status_code=413, detail="Upload exceeds the aggregate size limit")

    bulk_id = str(uuid4())
    bulk = TKPBulkUploadJob(
        id=bulk_id,
        workspace_id=str(access.workspace_id),
        owner_user_id=access.user.id,
    )
    db.add(bulk)
    db.flush()

    try:
        for upload in files:
            filename = PurePath((upload.filename or "").replace("\\", "/")).name
            document = TKPBulkUploadDocument(
                id=str(uuid4()),
                bulk_job_id=bulk_id,
                workspace_id=str(access.workspace_id),
                owner_user_id=access.user.id,
                filename=filename,
            )
            db.add(document)
            db.flush()
            try:
                body = await client.start_document_workflow(
                    filename,
                    upload.file,
                    upload.content_type or "application/octet-stream",
                    correlation_id,
                )
                job = _document_from_job(body)
                document.tkp_job_id = str(job.get("id")) if job.get("id") else None
                document.processing_status = str(job.get("processing_status") or "QUEUED")
                document.index_status = str(job.get("index_status") or "NOT_READY")
                document.retryable = bool(job.get("retryable"))
                document.error_code = job.get("error_code")
                document.error_message = job.get("error_message")
                source_version = job.get("source_version_id")
                revision = job.get("revision_id")
                document.source_version_id = str(source_version) if source_version else None
                document.revision_id = str(revision) if revision else None
            except TKPClientError as error:
                document.processing_status = "FAILED"
                document.index_status = "NOT_READY"
                document.retryable = bool(error.retryable)
                document.error_code = error.code
                document.error_message = error.public_message
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(bulk)
    return _aggregate(bulk, _documents(bulk_id, access, db))


@router.get("/{job_id}", response_model=None)
async def get_bulk_upload_status(
    request: Request,
    job_id: str = Path(min_length=1, max_length=36),
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
    db: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    _require_write(access)
    bulk = _job(job_id, access, db)
    correlation_id = _correlation_id(request)
    client = _client(request)
    documents = _documents(job_id, access, db)
    for document in documents:
        if not document.tkp_job_id:
            continue
        try:
            body = await client.document_workflow_status(document.tkp_job_id, correlation_id)
            job = _document_from_job(body)
            document.processing_status = str(
                job.get("processing_status") or document.processing_status
            )
            document.index_status = str(job.get("index_status") or document.index_status)
            document.retryable = bool(job.get("retryable"))
            document.error_code = job.get("error_code")
            document.error_message = job.get("error_message")
            source_version = job.get("source_version_id")
            revision = job.get("revision_id")
            document.source_version_id = (
                str(source_version) if source_version else document.source_version_id
            )
            document.revision_id = str(revision) if revision else document.revision_id
        except TKPClientError as error:
            document.error_code = error.code
            document.error_message = error.public_message
            document.retryable = bool(error.retryable)
    db.commit()
    return _aggregate(bulk, _documents(job_id, access, db))


@router.post("/{job_id}/retry", response_model=None)
async def retry_bulk_upload(
    request: Request,
    payload: RetryDocumentsRequest,
    job_id: str = Path(min_length=1, max_length=36),
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
    db: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    _require_write(access)
    bulk = _job(job_id, access, db)
    correlation_id = _correlation_id(request)
    client = _client(request)
    documents = _documents(job_id, access, db)
    requested = set(payload.document_ids)
    for document in documents:
        if document.id not in requested:
            continue
        if not document.retryable or not document.tkp_job_id:
            raise HTTPException(status_code=409, detail="Document is not retryable")
        try:
            body = await client.retry_document_workflow(document.tkp_job_id, correlation_id)
            job = _document_from_job(body)
            document.tkp_job_id = str(job.get("id")) if job.get("id") else document.tkp_job_id
            document.processing_status = str(job.get("processing_status") or "QUEUED")
            document.index_status = str(job.get("index_status") or "NOT_READY")
            document.retryable = bool(job.get("retryable"))
            document.error_code = job.get("error_code")
            document.error_message = job.get("error_message")
        except TKPClientError as error:
            document.error_code = error.code
            document.error_message = error.public_message
            document.retryable = bool(error.retryable)
    db.commit()
    return _aggregate(bulk, _documents(job_id, access, db))
