from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, chat, upload, billing,profile

app = FastAPI()

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(billing.router)
app.include_router(profile.router)


# 👇 Allow frontend (React) to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
