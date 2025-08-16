# app/main.py
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import (
    auth, chat, upload, billing, profile, auth_oauth,
    search, settings as settings_routes, admin, auth_password
)

logging.basicConfig(level=logging.INFO)
app = FastAPI()

# ✅ CORS first (use one host consistently: either localhost or 127.0.0.1)
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Routers
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(billing.router)
app.include_router(profile.router)
app.include_router(auth_oauth.router)
app.include_router(search.router)
app.include_router(settings_routes.router)
app.include_router(admin.router)
app.include_router(auth_password.router)

# (Optional) add health for quick checks without CORS drama
@app.get("/health")
def health():
    return {"ok": True}


