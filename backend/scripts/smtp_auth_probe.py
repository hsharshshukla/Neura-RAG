# scripts/smtp_auth_probe.py
import os, asyncio
from dotenv import load_dotenv
load_dotenv()

import aiosmtplib

async def main():
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    use_ssl = os.getenv("SMTP_SSL", "false").lower() in ("1","true","yes","on")
    starttls = os.getenv("SMTP_TLS", "true").lower() in ("1","true","yes","on")
    user = os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME")
    pwd = os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD")

    print(f"Connecting to {host}:{port} ssl={use_ssl} starttls={starttls}")
    smtp = aiosmtplib.SMTP(hostname=host, port=port, use_tls=use_ssl, timeout=15)
    await smtp.connect()
    if starttls and not use_ssl and not getattr(smtp, "is_tls", False):
        try:
            await smtp.starttls()
        except Exception as e:
            print("STARTTLS failed:", e)
            raise
    try:
        await smtp.login(user, pwd)
        print("LOGIN OK")
    finally:
        try: await smtp.quit()
        except: pass

asyncio.run(main())
