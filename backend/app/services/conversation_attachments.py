import re
import uuid

from sqlalchemy import text
from sqlmodel import Session


def attachment_document_id(user_id: int, session_id: int, sha256: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"conversation-attachment:{user_id}:{session_id}:{sha256}",
        )
    )


def completed_attachments(db: Session, *, user_id: int, session_id: int) -> dict[str, str]:
    rows = db.exec(
        text("""
            SELECT sha256, doc_id FROM public.upload_link
            WHERE user_id = :u AND session_id = :s
        """).bindparams(u=user_id, s=session_id)
    ).all()
    return {
        sha256: doc_id
        for sha256, doc_id in rows
        if isinstance(sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", sha256)
        and doc_id == attachment_document_id(user_id, session_id, sha256)
    }
