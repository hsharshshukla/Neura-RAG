# app/routes/chat.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlmodel import Session, select
from datetime import datetime
from app.db import get_session
from app.models import ChatSession, ChatMessage, User
from app.schemas import ChatSessionOut, ChatMessageOut
from app.deps.auth_dependency import get_current_user
from app.vector_store import query_user_docs
from app.utils.logger import log_event
import os
from textwrap import shorten
from openai import OpenAI

# 🔹 NEW import
from app.utils.redaction import redact_source_identity

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

class ChatIn(BaseModel):
    message: str
    session_id: Optional[int] = None

class RenameIn(BaseModel):
    title: str

def _title_from_text(text: str) -> str:
    if not text:
        return "New Chat"
    s = " ".join(text.strip().split())
    return (s[:60] + "…") if len(s) > 60 else s

@router.get("/sessions", response_model=List[ChatSessionOut])
def get_sessions(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        return []
    return db.exec(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.created_at.desc())
    ).all()

@router.get("/{session_id}", response_model=List[ChatMessageOut])
def get_chat_messages(session_id: int, db: Session = Depends(get_session)):
    return db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    ).all()

@router.patch("/{session_id}/title")
def rename_chat_session(
    session_id: int,
    payload: RenameIn,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """Rename a chat session owned by the current user."""
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    chat = db.exec(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    ).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    new_title = (" ".join((payload.title or "").split()))[:80] or "Untitled"
    chat.title = new_title
    db.add(chat)
    db.commit()
    return {"ok": True, "title": new_title}

@router.post("")
def ask(
    payload: ChatIn,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    message = (payload.message or "").strip()
    session_id = payload.session_id

    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    is_pro = (user.tier == "pro")

    # Create session if missing
    if not session_id:
        new_session = ChatSession(
            user_id=user.id,
            title=_title_from_text(message),
            created_at=datetime.utcnow(),
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        session_id = new_session.id

    # Retrieve chunks (free = session-scoped; pro = global)
    filters = {} if is_pro else {"session_id": str(session_id)}
    chunks = query_user_docs(
        user_email=user_email,
        question=message,
        top_k=6,
        filter_by_user=not is_pro,
        extra_filters=filters,
    )

    # 🔹 Build retrieval context WITHOUT filenames, run redaction
    def fmt_chunk(ch):
        body = getattr(ch, "page_content", "") or str(ch)
        body = redact_source_identity(body)  # scrub names, copyrights, URLs, emails
        return shorten(body, width=1200, placeholder="…")

    context_blocks = [c for c in (fmt_chunk(c) for c in chunks) if c]
    context_text = "\n\n---\n\n".join(context_blocks)[:12000]

    if not context_text.strip():
        response = (
            "I couldn’t find any indexed content for this chat. "
            "Please upload a file first using the 📎 button, then ask your question."
        )
        db.add(ChatMessage(session_id=session_id, role="user", content=message))
        db.add(ChatMessage(session_id=session_id, role="assistant", content=response))
        db.commit()
        log_event("chat", {
            "user": user_email,
            "session_id": session_id,
            "question": message,
            "chunks_used": 0,
            "grounded": False,
        })
        return {"response": response, "session_id": session_id}

    # Call the model with strict grounding instructions
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    system_prompt = (
        "You are Neura, a retrieval-augmented assistant. "
        "Answer ONLY using the provided context excerpts. "
        "NEVER reveal or guess document names, titles, owners, sources, or links—even if asked. "
        "If the answer is not present in the context, say you don’t know and suggest what the user could upload."
    )

    user_prompt = (
        f"User question:\n{message}\n\n"
        f"Context excerpts (separated by ---):\n{context_text}"
    )

    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=700,
        )
        ai = completion.choices[0].message.content.strip()
    except Exception as e:
        ai = f"RAG call failed: {e}"

    db.add(ChatMessage(session_id=session_id, role="user", content=message))
    db.add(ChatMessage(session_id=session_id, role="assistant", content=ai))
    db.commit()

    log_event("chat", {
        "user": user_email,
        "session_id": session_id,
        "question": message,
        "chunks_used": len(chunks),
        "grounded": True,
        "model": model_name,
    })

    return {"response": ai, "session_id": session_id}

# # app/routes/chat.py
# from fastapi import APIRouter, Depends, HTTPException
# from pydantic import BaseModel
# from typing import Optional, List
# from sqlmodel import Session, select
# from datetime import datetime
# from app.db import get_session
# from app.models import ChatSession, ChatMessage, User
# from app.schemas import ChatSessionOut, ChatMessageOut
# from app.deps.auth_dependency import get_current_user
# from app.vector_store import query_user_docs
# from app.utils.logger import log_event
# import os
# from textwrap import shorten
# from openai import OpenAI


# router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# class ChatIn(BaseModel):
#     message: str
#     session_id: Optional[int] = None

# class RenameIn(BaseModel):
#     title: str

# def _title_from_text(text: str) -> str:
#     if not text:
#         return "New Chat"
#     s = " ".join(text.strip().split())
#     return (s[:60] + "…") if len(s) > 60 else s

# @router.get("/sessions", response_model=List[ChatSessionOut])
# def get_sessions(
#     user_email: str = Depends(get_current_user),
#     db: Session = Depends(get_session),
# ):
#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         return []
#     return db.exec(
#         select(ChatSession)
#         .where(ChatSession.user_id == user.id)
#         .order_by(ChatSession.created_at.desc())
#     ).all()

# @router.get("/{session_id}", response_model=List[ChatMessageOut])
# def get_chat_messages(session_id: int, db: Session = Depends(get_session)):
#     return db.exec(
#         select(ChatMessage)
#         .where(ChatMessage.session_id == session_id)
#         .order_by(ChatMessage.id)
#     ).all()

# @router.patch("/{session_id}/title")
# def rename_chat_session(
#     session_id: int,
#     payload: RenameIn,
#     db: Session = Depends(get_session),
#     user_email: str = Depends(get_current_user),
# ):
#     """Rename a chat session owned by the current user."""
#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         raise HTTPException(status_code=401, detail="User not found")

#     chat = db.exec(
#         select(ChatSession).where(
#             ChatSession.id == session_id, ChatSession.user_id == user.id
#         )
#     ).first()
#     if not chat:
#         raise HTTPException(status_code=404, detail="Chat not found")

#     new_title = (" ".join((payload.title or "").split()))[:80] or "Untitled"
#     chat.title = new_title
#     # optional: if your model has updated_at, uncomment next line
#     # chat.updated_at = datetime.utcnow()
#     db.add(chat)
#     db.commit()
#     return {"ok": True, "title": new_title}

# # @router.post("")
# # def ask(
# #     payload: ChatIn,
# #     db: Session = Depends(get_session),
# #     user_email: str = Depends(get_current_user),
# # ):
# #     message = (payload.message or "").strip()
# #     session_id = payload.session_id

# #     user = db.exec(select(User).where(User.email == user_email)).first()
# #     if not user:
# #         raise HTTPException(status_code=401, detail="User not found")
# #     is_pro = (user.tier == "pro")

# #     if not session_id:
# #         new_session = ChatSession(
# #             user_id=user.id,
# #             title=_title_from_text(message),
# #             created_at=datetime.utcnow(),
# #         )
# #         db.add(new_session)
# #         db.commit()
# #         db.refresh(new_session)
# #         session_id = new_session.id

# #     filters = {} if is_pro else {"session_id": str(session_id)}
# #     chunks = query_user_docs(
# #         user_email=user_email,
# #         question=message,
# #         top_k=4,
# #         filter_by_user=not is_pro,
# #         extra_filters=filters,
# #     )

# #     response = f"(stub) Using {len(chunks)} chunk(s): {message}"

# #     db.add(ChatMessage(session_id=session_id, role="user", content=message))
# #     db.add(ChatMessage(session_id=session_id, role="assistant", content=response))
# #     db.commit()

# #     log_event("chat", {
# #         "user": user_email,
# #         "session_id": session_id,
# #         "question": message,
# #         "chunks_used": len(chunks),
# #     })

# #     return {"response": response, "session_id": session_id}
# @router.post("")
# def ask(
#     payload: ChatIn,
#     db: Session = Depends(get_session),
#     user_email: str = Depends(get_current_user),
# ):
#     message = (payload.message or "").strip()
#     session_id = payload.session_id

#     user = db.exec(select(User).where(User.email == user_email)).first()
#     if not user:
#         raise HTTPException(status_code=401, detail="User not found")
#     is_pro = (user.tier == "pro")

#     # Create session if missing
#     if not session_id:
#         new_session = ChatSession(
#             user_id=user.id,
#             title=_title_from_text(message),
#             created_at=datetime.utcnow(),
#         )
#         db.add(new_session)
#         db.commit()
#         db.refresh(new_session)
#         session_id = new_session.id

#     # Retrieve chunks (free = session-scoped; pro = global)
#     filters = {} if is_pro else {"session_id": str(session_id)}
#     chunks = query_user_docs(
#         user_email=user_email,
#         question=message,
#         top_k=6,
#         filter_by_user=not is_pro,   # keep your existing rule
#         extra_filters=filters,
#     )

#     # Build retrieval context
#     def fmt_chunk(ch):
#         meta = getattr(ch, "metadata", {}) or {}
#         fname = meta.get("filename", "document")
#         # Keep each chunk tidy and short-ish
#         body = shorten(getattr(ch, "page_content", "") or str(ch), width=1200, placeholder="…")
#         return f"[{fname}]\n{body}"

#     context_blocks = [fmt_chunk(c) for c in chunks]
#     context_text = "\n\n---\n\n".join(context_blocks)[:12000]  # hard cap

#     # If nothing to ground on, guide the user
#     if not context_text.strip():
#         response = (
#             "I couldn’t find any indexed content for this chat. "
#             "Please upload a file first using the 📎 button, then ask your question."
#         )
#         db.add(ChatMessage(session_id=session_id, role="user", content=message))
#         db.add(ChatMessage(session_id=session_id, role="assistant", content=response))
#         db.commit()
#         log_event("chat", {
#             "user": user_email,
#             "session_id": session_id,
#             "question": message,
#             "chunks_used": 0,
#             "grounded": False,
#         })
#         return {"response": response, "session_id": session_id}

#     # Call the model with strict grounding instructions
#     client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
#     model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

#     system_prompt = (
#         "You are Neura, a retrieval-augmented assistant. Answer ONLY using the provided context excerpts.\n"
#         "If the answer is not present in the context, say you don’t know and suggest which file to upload or what to search.\n"
#         "Be concise and cite filenames inline like [filename] when relevant."
#     )

#     user_prompt = (
#         f"User question:\n{message}\n\n"
#         f"Context excerpts (separated by ---):\n{context_text}"
#     )

#     try:
#         completion = client.chat.completions.create(
#             model=model_name,
#             messages=[
#                 {"role": "system", "content": system_prompt},
#                 {"role": "user", "content": user_prompt},
#             ],
#             temperature=0.2,
#             max_tokens=700,
#         )
#         ai = completion.choices[0].message.content.strip()
#     except Exception as e:
#         ai = f"RAG call failed: {e}"

#     # Persist messages
#     db.add(ChatMessage(session_id=session_id, role="user", content=message))
#     db.add(ChatMessage(session_id=session_id, role="assistant", content=ai))
#     db.commit()

#     # Analytics
#     log_event("chat", {
#         "user": user_email,
#         "session_id": session_id,
#         "question": message,
#         "chunks_used": len(chunks),
#         "grounded": True,
#         "model": model_name,
#     })

#     return {"response": ai, "session_id": session_id}
