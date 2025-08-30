# app/middleware/client_ctx.py
from __future__ import annotations
import os, ipaddress, json
from typing import Optional, TypedDict
from fastapi import Request
import httpx

class ClientCtx(TypedDict, total=False):
    ip: str
    country: Optional[str]
    is_vpn: bool
    is_hosting: bool
    is_tor: bool
    raw: dict

def _get_ip(req: Request) -> str:
    # Prefer proxy headers if you’re behind a reverse proxy
    xff = req.headers.get("x-forwarded-for", "")
    if xff:
        ip = xff.split(",")[0].strip()
    else:
        ip = req.client.host if req.client else "127.0.0.1"
    return ip

async def _fetch_ipinfo(ip: str, token: str) -> dict:
    url = f"https://ipinfo.io/{ip}?token={token}"
    async with httpx.AsyncClient(timeout=3.5) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()

async def build_client_ctx(req: Request) -> ClientCtx:
    ip = _get_ip(req)
    ctx: ClientCtx = {"ip": ip, "country": None, "is_vpn": False, "is_hosting": False, "is_tor": False, "raw": {}}

    # Local/dev bypass
    try:
        if ipaddress.ip_address(ip).is_private:
            ctx["country"] = os.getenv("DEV_DEFAULT_COUNTRY", "IN")
            return ctx
    except Exception:
        pass

    provider = (os.getenv("GEOIP_PROVIDER") or "ipinfo").lower()
    allow_vpn_in_dev = os.getenv("ALLOW_VPN_IN_DEV", "false").lower() in ("1", "true", "yes")

    try:
        if provider == "ipinfo":
            token = os.getenv("IPINFO_TOKEN", "")
            if token:
                data = await _fetch_ipinfo(ip, token)
                ctx["raw"] = data
                ctx["country"] = (data.get("country") or "").upper() or None
                priv = data.get("privacy") or {}
                ctx["is_vpn"] = bool(priv.get("vpn"))
                ctx["is_tor"] = bool(priv.get("tor"))
                ctx["is_hosting"] = bool(priv.get("hosting"))
        # You can add ipregistry / ip2location branches here similarly
    except Exception:
        # On provider error, fall back to no VPN signal; currency will default later
        pass

    # Optional global override to never block in dev
    if allow_vpn_in_dev:
        ctx["is_vpn"] = False
        ctx["is_tor"] = False
        ctx["is_hosting"] = False

    return ctx
