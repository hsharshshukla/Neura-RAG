from fastapi import APIRouter, Form, Depends, HTTPException
from sqlmodel import Session, select
from app.models import User
from app.db import get_session
from jose import jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


SECRET_KEY = "supersecretkey"
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ✅ REGISTER
@router.post("/signup")
def signup(
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(None),
    db: Session = Depends(get_session)
):
    existing = db.exec(select(User).where(User.email == email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = pwd_context.hash(password)
    user = User(
        email=email,
        password=hashed_password,
        tier="free",
        name=name or email.split("@")[0].capitalize(),
        created_at=datetime.utcnow()
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = jwt.encode(
        {"sub": user.email, "exp": datetime.utcnow() + timedelta(hours=24)},
        SECRET_KEY,
        algorithm=ALGORITHM
    )
    return {"email": user.email, "tier": user.tier, "access_token": token}


# ✅ LOGIN
@router.post("/login")
def login(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session)
):

    user = db.exec(select(User).where(User.email == email)).first()
    print("user details ------",user)
    if not user or not pwd_context.verify(password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = jwt.encode(
        {"sub": user.email, "exp": datetime.utcnow() + timedelta(hours=24)},
        SECRET_KEY,
        algorithm=ALGORITHM
    )
    return {"email": user.email, "tier": user.tier, "access_token": token}
