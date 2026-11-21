"""Replix Admin Panel — separate server.
Run with:  python -m admin.server
Defaults to port 8766. Set REPLIX_ADMIN_PORT to change it.
Only accessible from localhost unless REPLIX_ADMIN_HOST is set.
Protected by REPLIX_ADMIN_SECRET token (set in .env)."""
import hashlib
import hmac
import os
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

ROOT = Path(__file__).resolve().parent.parent


def _env(key, default=""):
    return os.environ.get(key, default).strip()


def _load_dotenv():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

ADMIN_PORT = int(_env("REPLIX_ADMIN_PORT", "8766"))
ADMIN_HOST = _env("REPLIX_ADMIN_HOST", "127.0.0.1")
ADMIN_SECRET = _env("REPLIX_ADMIN_SECRET", "")   # optional bearer token guard
MAIN_API = _env("REPLIX_MAIN_URL", "http://127.0.0.1:8765")

ADMIN_DIR = ROOT / "admin"
WEB_DIR = ROOT / "web"

app = FastAPI(title="Replix Admin", docs_url=None, redoc_url=None, openapi_url=None)


class AdminGate:
    """Simple gate: check optional bearer secret, redirect to main app login if not set."""
    def __init__(self, app):
        self.inner = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        from starlette.requests import Request as R
        req = R(scope)
        path = scope["path"]

        # Static brand assets — always open
        if path.startswith("/brand/"):
            return await self.inner(scope, receive, send)

        # Optional secret check
        if ADMIN_SECRET:
            token = req.cookies.get("admin_token", "") or req.headers.get("x-admin-token", "")
            if not hmac.compare_digest(token, ADMIN_SECRET):
                if path == "/auth":
                    return await self.inner(scope, receive, send)
                resp = RedirectResponse("/auth", 303)
                await resp(scope, receive, send)
                return

        await self.inner(scope, receive, send)


app.add_middleware(AdminGate)


@app.get("/auth")
def auth_page(request: Request):
    """Simple password page when REPLIX_ADMIN_SECRET is set."""
    secret = request.query_params.get("s", "")
    if ADMIN_SECRET and hmac.compare_digest(secret, ADMIN_SECRET):
        resp = RedirectResponse("/", 303)
        resp.set_cookie("admin_token", ADMIN_SECRET, httponly=True, samesite="strict", max_age=86400 * 30)
        return resp
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Replix Admin</title>
<link rel="icon" href="/brand/favicon.ico">
<style>*{{box-sizing:border-box;margin:0}}body{{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0A0106;font-family:system-ui}}
.c{{background:#1A0510;border:1px solid rgba(232,39,58,.2);border-radius:16px;padding:32px;width:360px;text-align:center}}
h2{{color:#fff;margin-bottom:8px;font-size:20px}}p{{color:rgba(255,255,255,.5);font-size:13px;margin-bottom:20px}}
input{{width:100%;height:44px;padding:0 14px;border-radius:10px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.05);color:#fff;font-size:15px;margin-bottom:12px}}
button{{width:100%;height:44px;background:#E8273A;border:0;border-radius:10px;color:#fff;font-size:15px;font-weight:700;cursor:pointer}}</style>
</head><body><div class="c"><h2>Replix Admin</h2><p>Enter admin secret to continue</p>
<form method="get"><input type="password" name="s" placeholder="Admin secret" autofocus><button>Enter</button></form></div></body></html>"""
    return HTMLResponse(html, status_code=401 if request.query_params.get("s") else 200)


@app.get("/brand/{name}")
def brand(name: str):
    import re
    if not re.fullmatch(r"[\w\-]+\.(svg|png|ico|webp|jpg)", name):
        return HTMLResponse("Not found", 404)
    f = WEB_DIR / "brand" / name
    if not f.is_file():
        return HTMLResponse("Not found", 404)
    return FileResponse(f, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "replix-admin"}


@app.get("/{rest:path}")
def admin_catch_all(rest: str = ""):
    f = ADMIN_DIR / "index.html"
    if f.exists():
        return FileResponse(f, headers={"Cache-Control": "private, no-cache"})
    return HTMLResponse("<h1>Admin panel not found</h1>", 404)


def main():
    print(f"\n  Replix Admin running:  http://{ADMIN_HOST}:{ADMIN_PORT}\n")
    if ADMIN_SECRET:
        print(f"  Protected. Open: http://{ADMIN_HOST}:{ADMIN_PORT}/auth?s=YOUR_SECRET\n")
    uvicorn.run(app, host=ADMIN_HOST, port=ADMIN_PORT, log_level="warning")


if __name__ == "__main__":
    main()
