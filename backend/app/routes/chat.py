# chat.py — Handles user messages, retrieves relevant chunks, and generates GPT responses
from fastapi import APIRouter, Form, Depends
from sqlmodel import Session, select
from app.db import get_session
from app.models import ChatSession, ChatMessage, User
from app.schemas import ChatSessionOut, ChatMessageOut
from app.deps.auth_dependency import get_current_user
from app.vector_store import query_user_docs
from app.utils.logger import log_event
from openai import ChatCompletion
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

@router.get("/sessions", response_model=List[ChatSessionOut])
def get_sessions(user_email: str = Depends(get_current_user), db: Session = Depends(get_session)):
    return db.query(ChatSession).filter(ChatSession.user_email == user_email).order_by(ChatSession.created_at.desc()).all()

@router.get("/{session_id}", response_model=List[ChatMessageOut])
def get_chat_messages(session_id: int, db: Session = Depends(get_session)):
    return db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at).all()

@router.post("")
def ask(
    message: str = Form(...),
    session_id: Optional[int] = Form(None),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user)
):
    # 🧠 Retrieve user tier
    user = db.exec(select(User).where(User.email == user_email)).first()
    is_pro = user.tier == "pro"

    # 🧠 Get relevant chunks
    filters = {} if is_pro else {"session_id": str(session_id)}
    chunks = query_user_docs(
        user_email=user_email,
        question=message,
        top_k=4,
        filter_by_user=not is_pro,
        extra_filters=filters
    )
    context = "\n\n".join([c.page_content for c in chunks])

    # 🤖 Ask GPT using the chunks
    completion = ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Answer only using the provided context. Do not mention any document names, companies, or sources."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {message}"}
        ]
    )
    response = completion["choices"][0]["message"]["content"]

    # 📝 Log chat
    if not session_id:
        new_session = ChatSession(user_email=user_email, title="New Chat", created_at=datetime.utcnow())
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        session_id = new_session.id

    db.add(ChatMessage(session_id=session_id, role="user", content=message))
    db.add(ChatMessage(session_id=session_id, role="assistant", content=response))
    db.commit()

    # 📊 Log event
    log_event("chat", {
        "user": user_email,
        "session_id": session_id,
        "question": message,
        "chunks_used": len(chunks)
    })

    return {"response": response, "session_id": session_id}
