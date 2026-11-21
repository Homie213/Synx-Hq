"""Send structured log messages to Discord webhooks for monitoring."""
import threading
import time
from typing import Literal

import httpx

from . import config

WebhookKind = Literal["server", "error", "other"]


def _url(kind: WebhookKind) -> str:
    # Read dynamically from os.environ or Supabase vault cache so startup timing doesn't leave them empty
    import os
    env = os.environ.get
    from . import secrets
    val = {
        "server": env("REPLIX_DISCORD_SERVER_LOGS") or secrets.get("discord_server_logs"),
        "error": env("REPLIX_DISCORD_ERROR_LOGS") or secrets.get("discord_error_logs"),
        "other": env("REPLIX_DISCORD_OTHER_LOGS") or secrets.get("discord_other_logs"),
    }.get(kind, "")
    return (val or "").strip()


def send(message: str, kind: WebhookKind = "other", title: str = "", color: int = 0x2ECC71) -> None:
    """Fire-and-forget Discord webhook. Never raises."""
    url = _url(kind)
    if not url:
        return

    def _post():
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            payload = {
                "embeds": [{
                    "title": title or {"server": "\U0001f7e2 Server Log", "error": "\U0001f534 Error", "other": "\U0001f4cb Log"}[kind],
                    "description": str(message)[:4000],
                    "color": color,
                    "footer": {"text": f"Replix \u00b7 {ts}"}
                }]
            }
            httpx.post(url, json=payload, timeout=8)
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


def server_log(msg: str, title: str = ""):
    send(msg, "server", title, color=0x3498DB)


def error_log(msg: str, title: str = "Error"):
    send(msg, "error", title, color=0xE8273A)


def other_log(msg: str, title: str = ""):
    send(msg, "other", title, color=0x9B59B6)
