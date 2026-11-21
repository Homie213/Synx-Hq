"""Admin OTP via Discord webhook.
When an admin tries to log in, a 6-digit OTP is sent to Discord instead of email.
The admin enters the OTP in the browser to complete login.
"""
import hashlib
import secrets
import time
import threading
from typing import Optional

import httpx

from . import config

# In-memory OTP store: {email: (otp_hash, expires_at, attempts)}
_otps: dict = {}
_lock = threading.Lock()

OTP_TTL = 300        # 5 minutes
OTP_MAX_TRIES = 5    # max wrong attempts before invalidation


def _h(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def generate_and_send(email: str, name: str = "") -> bool:
    """Generate OTP, send to Discord, store hashed. Returns True if sent."""
    from . import discord_log
    webhook = discord_log._url("server") or discord_log._url("other")
    if not webhook:
        return False

    otp = str(secrets.randbelow(900000) + 100000)   # 6-digit
    expires = time.time() + OTP_TTL

    with _lock:
        _otps[email] = (_h(otp), expires, 0)

    # Send to Discord
    def _send():
        try:
            payload = {
                "embeds": [{
                    "title": "🔐 Admin Login OTP",
                    "description": (
                        f"**Email:** `{email}`\n"
                        f"**Name:** {name or 'Unknown'}\n\n"
                        f"**OTP Code:**\n"
                        f"```\n{otp}\n```\n"
                        f"⏱️ Expires in 5 minutes.\n"
                        f"🚫 Do NOT share this code."
                    ),
                    "color": 0xE8273A,
                    "footer": {"text": f"Replix Admin · {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"}
                }]
            }
            httpx.post(webhook, json=payload, timeout=10)
        except Exception as e:
            print(f"[OTP] Discord send failed: {e}", flush=True)

    threading.Thread(target=_send, daemon=True).start()
    return True


def verify(email: str, otp: str) -> bool:
    """Verify OTP. Returns True if correct and not expired."""
    otp = otp.strip()
    with _lock:
        entry = _otps.get(email)
        if not entry:
            return False
        otp_hash, expires, attempts = entry

        if time.time() > expires:
            del _otps[email]
            return False

        if attempts >= OTP_MAX_TRIES:
            del _otps[email]
            return False

        if not _h(otp) == otp_hash:
            _otps[email] = (otp_hash, expires, attempts + 1)
            return False

        # Correct — consume it
        del _otps[email]
        return True


def has_pending(email: str) -> bool:
    with _lock:
        entry = _otps.get(email)
        if not entry:
            return False
        _, expires, _ = entry
        if time.time() > expires:
            del _otps[email]
            return False
        return True


def clear(email: str):
    with _lock:
        _otps.pop(email, None)
