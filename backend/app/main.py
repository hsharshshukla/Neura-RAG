# app/main.py
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routes import auth, chat, upload, billing, profile, auth_oauth , search, settings as settings_routes,admin, auth_password  # your new reset routes

logging.basicConfig(level=logging.INFO)
app = FastAPI()

# ✅ CORS first
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ✅ Routers (no duplicates)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(billing.router)
app.include_router(profile.router)
app.include_router(auth_oauth.router)  # NEW
app.include_router(search.router)
app.include_router(settings_routes.router)
app.include_router(admin.router)
app.include_router(auth_password.router)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logging.info(f"📥 {request.method} {request.url}")
    try:
        response = await call_next(request)
    except Exception as e:
        logging.exception("Unhandled error")
        # Return a controlled 500 so CORS headers still attach
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("Internal Server Error", status_code=500)
    logging.info(f"📤 {response.status_code}")
    return response


