import smtplib
from email.message import EmailMessage
import os

FROM = os.getenv("FROM_EMAIL", "no-reply@neura.app")

def send_password_reset_email(to_email: str, reset_link: str):
    # Dev mode: log only (no SMTP)
    if os.getenv("DEV_EMAIL_LOG_ONLY", "true").lower() == "true":
        print(f"[DEV MAIL] Reset link for {to_email}: {reset_link}")
        return

    host = os.getenv("SMTP_HOST"); port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER"); pwd = os.getenv("SMTP_PASS")

    msg = EmailMessage()
    msg["From"] = FROM
    msg["To"] = to_email
    msg["Subject"] = "Reset your Neura password"
    msg.set_content(f"Click to reset your password: {reset_link}\nIf you didn't request this, you can ignore this email.")

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
