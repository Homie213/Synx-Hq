"""Health check, keep-alive pings, and periodic system audit sent to Discord."""
import threading
import time

import httpx

from . import config, discord_log as dlog


REND_KEEPALIVE_URL = config.KEEPALIVE_URL
AUDIT_INTERVAL = 3600   # audit every hour
PING_INTERVAL = 240     # ping every 4 minutes to prevent sleep


def _ping_loop():
    """Ping the app's own /healthz to prevent Render free tier sleep."""
    if not REND_KEEPALIVE_URL:
        return
    while True:
        try:
            httpx.get(REND_KEEPALIVE_URL.rstrip("/") + "/healthz", timeout=10)
        except Exception:
            pass
        time.sleep(PING_INTERVAL)


def _audit_loop():
    """Hourly audit: check DB, disk, jobs, and report to Discord."""
    time.sleep(60)  # wait 1 minute after startup before first audit
    while True:
        try:
            _run_audit()
        except Exception as e:
            dlog.error_log(f"Audit failed: {e}", "\u26a0\ufe0f Audit Error")
        time.sleep(AUDIT_INTERVAL)


def _run_audit():
    from . import jobs, load, db
    import sqlalchemy as sa
    import os
    import shutil

    lines = ["**Replix Hourly Audit**\n"]

    # DB check
    try:
        with db.engine.connect() as c:
            user_count = c.execute(sa.text("SELECT COUNT(*) FROM users")).scalar()
            job_count = c.execute(sa.text("SELECT COUNT(*) FROM usage WHERE t > extract(epoch from now()) - 86400")).scalar()
        lines.append(f"\u2705 Database: OK \u00b7 {user_count} users \u00b7 {job_count} AI calls today")
    except Exception as e:
        lines.append(f"\u274c Database: {e}")
        dlog.error_log(f"DB check failed: {e}", "\U0001f534 DB Error")

    # Disk check
    try:
        total, used, free = shutil.disk_usage(str(config.DATA_DIR))
        pct = int(used / total * 100)
        lines.append(f"\U0001f4be Disk: {free // (1024**3):.1f}GB free ({pct}% used)")
        if pct > 85:
            dlog.error_log(f"Disk is {pct}% full! Only {free//(1024**2)}MB free.", "\u26a0\ufe0f Low Disk")
    except Exception as e:
        lines.append(f"\u26a0\ufe0f Disk check failed: {e}")

    # Active jobs
    try:
        active = jobs.busy_count()
        lines.append(f"\u2699\ufe0f Active jobs: {active}")
    except Exception as e:
        lines.append(f"\u26a0\ufe0f Jobs check: {e}")

    # Load
    try:
        busy = load.busy()
        lines.append(f"\U0001f5a5\ufe0f System busy: {busy}")
    except Exception as e:
        lines.append(f"\u26a0\ufe0f Load check: {e}")

    dlog.other_log("\n".join(lines), "\U0001f4ca Hourly Audit")


def start():
    if config.DISCORD_OTHER_LOGS or config.DISCORD_SERVER_LOGS:
        threading.Thread(target=_audit_loop, daemon=True).start()
    if REND_KEEPALIVE_URL:
        threading.Thread(target=_ping_loop, daemon=True).start()
