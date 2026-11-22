from __future__ import annotations

from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.db import get_session
from app.deps.workspace import WorkspaceAccess, require_tkp_workspace_access
from app.integrations.tkp.client import TKPClientError, TKPIngestionClient
from app.integrations.tkp.schemas import MetadataReviewMutation, TKPMetadataReviewResponse
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
            "details": error.details,
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


def _document(
    job_id: str,
    document_id: str,
    access: WorkspaceAccess,
    db: Session,
) -> TKPBulkUploadDocument:
    _job(job_id, access, db)
    value = db.exec(
        select(TKPBulkUploadDocument).where(
            TKPBulkUploadDocument.id == document_id,
            TKPBulkUploadDocument.bulk_job_id == job_id,
            TKPBulkUploadDocument.workspace_id == str(access.workspace_id),
            TKPBulkUploadDocument.owner_user_id == access.user.id,
        )
    ).first()
    if value is None:
        raise HTTPException(status_code=404, detail="Unknown document_id")
    if not value.source_id or not value.source_version_id:
        raise HTTPException(status_code=409, detail="Document review is not available")
    return value


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
                "source_id": document.source_id,
                "source_version_id": document.source_version_id,
                "revision_id": document.revision_id,
                "metadata_review_available": bool(
                    document.source_id and document.source_version_id
                ),
            }
            for document in documents
        ],
    }


def _document_scope(document: TKPBulkUploadDocument) -> tuple[UUID, UUID]:
    try:
        return UUID(document.source_id or ""), UUID(document.source_version_id or "")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Document review is not available") from exc


def _review_response(
    response: TKPMetadataReviewResponse,
    document: TKPBulkUploadDocument,
    access: WorkspaceAccess,
) -> dict[str, Any]:
    view = response.metadata_verification
    root = view.verification
    source_id, version_id = _document_scope(document)
    if (
        root.workspace_id != access.workspace_id
        or root.source_id != source_id
        or root.version_id != version_id
        or root.contract_version != "document-metadata-verification-v1"
    ):
        raise HTTPException(status_code=502, detail="Metadata verification ownership mismatch")

    policy = root.policy
    review_required = root.review_required and policy.mode != "NEVER"
    fields = []
    for key in (root.review_fields if review_required else ()):
        rule = policy.field_rules[key]
        fields.append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "value_type": rule.value_type,
                "original_value": root.initial_draft.get(key),
                "draft_value": view.draft.get(key),
                "required": key in policy.required_fields,
                "read_only": False,
                "allowed_values": list(rule.allowed_values),
                "confidence": policy.confidence_values.get(key),
            }
        )
    actions = {
        "DRAFT": ["save_draft", "verify"],
        "VERIFIED": ["submit"],
        "SUBMITTED": [],
    }[view.verification_state]
    if not review_required:
        actions = []
    return {
        "review": {
            "source_id": str(root.source_id),
            "source_version_id": str(root.version_id),
            "source_file_id": str(root.source_file_id),
            "extraction_id": str(root.extraction_id),
            "verification_id": str(root.id),
            "filename": root.original_filename,
            "document_format": root.document_format,
            "contract_version": root.contract_version,
            "policy_id": policy.policy_id,
            "policy_version": policy.version,
            "verification_mode": policy.mode,
            "confidence_threshold": policy.confidence_threshold,
            "review_required": review_required,
            "expected_version": view.version,
            "review_status": view.verification_state,
            "verification_status": view.verification_state,
            "processing_status": document.processing_status,
            "index_status": view.index_state,
            "reviewable": review_required and bool(fields),
            "no_review_required": not review_required,
            "allowed_actions": actions,
            "selected_fields": [
                {
                    "key": key,
                    "confidence": policy.confidence_values.get(key),
                    "confidence_supplied": key in policy.confidence_values,
                }
                for key in root.selected_fields
            ],
            "derived_review_fields": list(root.review_fields) if review_required else [],
            "review_fields": fields,
            "preview_url": (
                f"/admin/bulk-upload/{document.bulk_job_id}/documents/"
                f"{document.id}/metadata-review/original"
            ),
            "audit_history": [
                {
                    "id": str(event.id),
                    "action": event.action,
                    "sequence": event.sequence_number,
                    "actor": str(event.actor_id),
                    "timestamp": event.created_at,
                }
                for event in view.history
            ],
        },
        "replayed": response.replayed,
        "correlation_id": str(response.correlation_id),
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
                source = job.get("source_id")
                source_version = job.get("source_version_id")
                revision = job.get("revision_id")
                document.source_id = str(source) if source else None
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
            source = job.get("source_id")
            source_version = job.get("source_version_id")
            revision = job.get("revision_id")
            document.source_id = str(source) if source else document.source_id
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
            source = job.get("source_id")
            source_version = job.get("source_version_id")
            revision = job.get("revision_id")
            document.source_id = str(source) if source else document.source_id
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


@router.get(
    "/{job_id}/documents/{document_id}/metadata-review",
    response_model=None,
)
async def get_metadata_review(
    request: Request,
    job_id: str = Path(min_length=1, max_length=36),
    document_id: str = Path(min_length=1, max_length=36),
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
    db: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    _require_write(access)
    document = _document(job_id, document_id, access, db)
    correlation_id = _correlation_id(request)
    source_id, version_id = _document_scope(document)
    try:
        response = await _client(request).metadata_review(
            source_id, version_id, correlation_id
        )
    except TKPClientError as error:
        return _error_response(error)
    return _review_response(response, document, access)


@router.post(
    "/{job_id}/documents/{document_id}/metadata-review/start",
    response_model=None,
)
async def start_metadata_review(
    request: Request,
    job_id: str = Path(min_length=1, max_length=36),
    document_id: str = Path(min_length=1, max_length=36),
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
    db: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    _require_write(access)
    document = _document(job_id, document_id, access, db)
    source_id, version_id = _document_scope(document)
    correlation_id = _correlation_id(request)
    try:
        response = await _client(request).start_metadata_review(
            source_id, version_id, uuid4(), correlation_id
        )
    except TKPClientError as error:
        return _error_response(error)
    return _review_response(response, document, access)


@router.get(
    "/{job_id}/documents/{document_id}/metadata-review/original",
    response_model=None,
)
async def get_metadata_review_original(
    request: Request,
    job_id: str = Path(min_length=1, max_length=36),
    document_id: str = Path(min_length=1, max_length=36),
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
    db: Session = Depends(get_session),
) -> Response:
    _require_write(access)
    document = _document(job_id, document_id, access, db)
    source_id, version_id = _document_scope(document)
    try:
        original = await _client(request).original_document(
            source_id, version_id, _correlation_id(request)
        )
    except TKPClientError as error:
        return _error_response(error)
    headers: dict[str, str] = {}
    if original.content_disposition:
        headers["Content-Disposition"] = original.content_disposition
    if original.source_sha256:
        headers["X-TKP-Source-Sha256"] = original.source_sha256
    return Response(
        content=original.content,
        media_type=original.content_type,
        headers=headers,
    )


@router.post(
    "/{job_id}/documents/{document_id}/metadata-review/{action}",
    response_model=None,
)
async def transition_metadata_review(
    request: Request,
    payload: MetadataReviewMutation,
    job_id: str = Path(min_length=1, max_length=36),
    document_id: str = Path(min_length=1, max_length=36),
    action: str = Path(pattern="^(save-draft|verify|submit)$"),
    access: WorkspaceAccess = Depends(require_tkp_workspace_access),
    db: Session = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    _require_write(access)
    document = _document(job_id, document_id, access, db)
    correlation_id = _correlation_id(request)
    source_id, version_id = _document_scope(document)
    try:
        current = await _client(request).metadata_review(
            source_id, version_id, correlation_id
        )
        _review_response(current, document, access)
        response = await _client(request).metadata_review_transition(
            current.metadata_verification.verification.id,
            action,
            payload,
            correlation_id,
        )
    except TKPClientError as error:
        return _error_response(error)
    return _review_response(response, document, access)
