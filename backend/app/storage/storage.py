# app/storage/storage.py
import os
import uuid
from pathlib import Path
from typing import Optional, Tuple

from app.config import (
    STORAGE_BACKEND, DOC_STORAGE_PATH,
    S3_BUCKET, S3_REGION, S3_ENDPOINT_URL,
    S3_FORCE_PATH_STYLE, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
)

def _ext_from_name(name: str) -> str:
    return (Path(name or "").suffix or "").lower()

class StorageResult(Tuple[str, str]):
    """
    (doc_id, uri)
    doc_id: opaque UUID string
    uri: backend-specific locator (e.g., file://... or s3://bucket/key)
    """
    pass

class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)
    
    def save_stream(self, user_id: int, session_id: int, filename: str, stream, mime=None):
        stream.seek(0)
        data = stream.read()
        return self.save(
            user_id=user_id,
            session_id=session_id,
            filename=filename,
            data=data
        )


    def save(self, *, user_id: int, session_id: int, filename: str, data: bytes) -> StorageResult:
        ext = _ext_from_name(filename)
        doc_id = str(uuid.uuid4())
        # Avoid leaking names: store only doc_id + extension
        rel = Path(str(user_id)) / str(session_id) / f"{doc_id}{ext}"
        abs_path = self.root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(data)
        return doc_id, f"file://{abs_path.resolve()}"

class S3Storage:
    def __init__(self):
        import boto3  # pip install boto3
        session = boto3.session.Session(
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=S3_REGION,
        )
        self.s3 = session.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            config=None
        )
    def save_stream(self, user_id: int, session_id: int, filename: str, stream, mime=None):
        import mimetypes
        stream.seek(0)
        data = stream.read()

        ext = _ext_from_name(filename)
        doc_id = str(uuid.uuid4())
        key = f"uploads/{user_id}/{session_id}/{doc_id}{ext}"

        content_type = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        self.s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type
        )

        return doc_id, f"s3://{S3_BUCKET}/{key}"


    def save(self, *, user_id: int, session_id: int, filename: str, data: bytes) -> StorageResult:
        import mimetypes
        ext = _ext_from_name(filename)
        doc_id = str(uuid.uuid4())
        key = f"uploads/{user_id}/{session_id}/{doc_id}{ext}"
        content_type = mimetypes.guess_type(f"dummy{ext}")[0] or "application/octet-stream"
        put_kwargs = {
            "Bucket": S3_BUCKET,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
        }
        # For MinIO/path-style
        if S3_FORCE_PATH_STYLE and hasattr(self.s3, "_endpoint"):
            # nothing else needed; kept for explicitness
            pass
        self.s3.put_object(**put_kwargs)
        return doc_id, f"s3://{S3_BUCKET}/{key}"

def get_storage():
    if STORAGE_BACKEND == "s3":
        return S3Storage()
    # default
    return LocalStorage(DOC_STORAGE_PATH)
