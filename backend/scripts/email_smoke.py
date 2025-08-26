from __future__ import annotations
import os, asyncio
from dotenv import load_dotenv

# load .env so SMTP_* and EMAIL_* are available when running standalone
load_dotenv()

from app.email.service import make_default_service, render_template, make_from_env
from app.email.models import EmailMessage, EmailAddress

async def main():
    svc = make_default_service()
    frm = make_from_env()

    # Ensure app/email/templates/welcome.html and welcome.txt exist,
    # or replace with inline bodies below.
    html, txt = render_template("welcome", user_name="You", dashboard_url="https://neurokron.com")

    msg = EmailMessage(
        subject="SMTP smoke test",
        **{"from": frm},
        to=[EmailAddress(email=os.getenv("TEST_TO", "viruj8154@gmail.com"), name="You")],
        html=html,
        text=txt,
        headers={"X-Debug": "neura"},
    )
    res = await svc.send(msg)
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
