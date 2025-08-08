from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

@router.post("/webhook")
async def handle_webhook(request: Request):
    event = await request.json()
    return { "status": "received", "event_type": event.get("event_name") }
