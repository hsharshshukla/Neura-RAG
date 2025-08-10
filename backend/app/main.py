# app/main.py
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routes import auth, chat, upload, billing, profile, auth_oauth   # NEW

# ...


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


# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from app.routes import auth, chat, upload, billing,profile
# from fastapi import FastAPI, Request
# import logging
# from app.routes import upload

# logging.basicConfig(level=logging.INFO)

# app = FastAPI()

# app.include_router(auth.router)
# app.include_router(chat.router)
# app.include_router(upload.router)
# app.include_router(billing.router)
# app.include_router(profile.router)
# app.include_router(upload.router)


# # 👇 Allow frontend (React) to talk to this backend
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["http://localhost:3000","http://127.0.0.1:3000"],  # React dev server
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# print("REqeeust izzz -- ",Request)
# @app.middleware("http")
# async def log_requests(request: Request, call_next):
#     logging.info(f"📥 Incoming request: {request.method} {request.url}")
#     response = await call_next(request)
#     logging.info(f"📤 Response status: {response.status_code}")
#     return response

