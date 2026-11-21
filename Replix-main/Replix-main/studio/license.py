"""License key validation, HWID fingerprinting, and activation for Replix."""
import hashlib
import platform
import secrets
import string
import time
import uuid

import sqlalchemy as sa

from . import config, db


# ---------------------------------------------------------------- HWID
def get_hwid() -> str:
    """Stable machine fingerprint — survives reboots, changes on hardware swap."""
    import os
    parts = [
        platform.node(),
        str(uuid.getnode()),
        platform.processor(),
        os.environ.get("USERNAME", os.environ.get("USER", "")),
        platform.machine(),
    ]
    raw = "|".join(p.strip() for p in parts if p.strip())
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------- key generation
def generate_key() -> str:
    chars = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    return "REPLIX-" + "-".join(parts)


# ---------------------------------------------------------------- license status
def license_status(user_id: str, hwid: str = "") -> dict:
    now = time.time()
    lk, la = db.license_keys.c, db.license_activations.c
    hwid = (hwid or "").strip()
    with db.engine.connect() as c:
        row = None
        base = (
            sa.select(db.license_keys, db.license_activations)
            .join(db.license_activations, lk.key == la.key)
            .where(la.user_id == user_id,
                   la.revoked == False, lk.revoked == False)
        )
        if hwid:
            row = c.execute(
                base.where(la.hwid == hwid).order_by(la.activated_at.desc()).limit(1)
            ).first()
        if not row:
            row = c.execute(
                base.order_by(la.activated_at.desc()).limit(1)
            ).first()

    if not row:
        return {"active": False, "reason": "no_license"}
    m = dict(row._mapping)
    if m.get("expires_at") and m["expires_at"] < now:
        return {"active": False, "reason": "expired", "expired_at": m["expires_at"]}
    days_left = None
    if m.get("expires_at"):
        days_left = max(0, int((m["expires_at"] - now) / 86400))
    return {
        "active": True,
        "plan": m["plan"],
        "expires_at": m.get("expires_at"),
        "days_left": days_left,
        "key_prefix": m["key"][:12] + "...",
        "device_name": m.get("device_name", ""),
        "activation_id": m["id"],
    }


# ---------------------------------------------------------------- activation
class LicenseError(ValueError):
    def __init__(self, msg, code="error"):
        super().__init__(msg)
        self.code = code


def activate(key: str, user_id: str, hwid: str, device_name: str = "") -> dict:
    key = key.strip().upper()
    now = time.time()
    lk, la = db.license_keys.c, db.license_activations.c
    is_new = False

    with db.engine.begin() as c:
        krow = c.execute(sa.select(db.license_keys).where(lk.key == key)).first()
        if not krow:
            raise LicenseError("That key doesn't exist. Check for typos.", "invalid_key")
        km = dict(krow._mapping)
        if km["revoked"]:
            raise LicenseError("This key has been revoked. Contact support on Discord.", "revoked")
        if km.get("expires_at") and km["expires_at"] < now:
            raise LicenseError("This key has expired.", "expired")

        # re-activation: same user+hwid
        existing = c.execute(
            sa.select(db.license_activations)
            .where(la.key == key, la.user_id == user_id,
                   la.hwid == hwid, la.revoked == False)
        ).first()
        if existing:
            c.execute(db.license_activations.update()
                      .where(db.license_activations.c.id == existing._mapping["id"])
                      .values(last_seen=now))
        else:
            # HWID bound to different user
            hwid_other = c.execute(
                sa.select(db.license_activations)
                .where(la.hwid == hwid, la.user_id != user_id, la.revoked == False)
            ).first()
            if hwid_other:
                raise LicenseError(
                    "This device is already registered to another account. "
                    "To unlink it, contact us on Discord: discord.gg/2t8rXUdgQ4",
                    "device_taken"
                )

            # max devices
            active_count = c.execute(
                sa.select(sa.func.count()).select_from(db.license_activations)
                .where(la.key == key, la.revoked == False)
            ).scalar() or 0
            if active_count >= km["max_devices"]:
                raise LicenseError(
                    f"This key is already active on {km['max_devices']} device(s). "
                    "Contact us on Discord to unlink an old device: discord.gg/2t8rXUdgQ4",
                    "max_devices"
                )

            # activate
            c.execute(db.license_activations.insert().values(
                key=key, user_id=user_id, hwid=hwid,
                activated_at=now, last_seen=now,
                device_name=(device_name or platform.node())[:200],
                revoked=False,
            ))
            is_new = True

    # Log to Discord ONLY on a brand-new activation (avoid duplicate spam on re-checks)
    if is_new:
        try:
            from . import discord_log
            discord_log.server_log(
                f"**User**: `{user_id}`\n**Plan**: `{km.get('plan', 'lifetime')}`\n**Device**: `{device_name or 'Desktop'}`\n**Key**: `{key[:12]}...`",
                "🎉 License Activated"
            )
        except Exception:
            pass

    return license_status(user_id, hwid)


# ---------------------------------------------------------------- admin helpers
def admin_list_keys(limit: int = 500) -> list:
    lk, la = db.license_keys.c, db.license_activations.c
    now = time.time()
    with db.engine.connect() as c:
        rows = c.execute(sa.select(db.license_keys)
                         .order_by(lk.created_at.desc()).limit(limit)).all()
        counts = {r[0]: r[1] for r in c.execute(
            sa.select(la.key, sa.func.count())
            .select_from(db.license_activations)
            .where(la.revoked == False).group_by(la.key)
        )}
    return [{
        "key": m["key"], "plan": m["plan"],
        "created_at": m["created_at"], "expires_at": m["expires_at"],
        "max_devices": m["max_devices"], "note": m["note"],
        "revoked": m["revoked"],
        "active_devices": counts.get(m["key"], 0),
        "expired": bool(m.get("expires_at") and m["expires_at"] < now),
    } for m in (dict(r._mapping) for r in rows)]


def admin_create_key(plan: str, duration_days, max_devices: int,
                     note: str, admin_id: str) -> str:
    key = generate_key()
    now = time.time()
    expires = (now + int(duration_days) * 86400) if duration_days else None
    with db.engine.begin() as c:
        c.execute(db.license_keys.insert().values(
            key=key, plan=plan, created_at=now, expires_at=expires,
            max_devices=max(1, max_devices), created_by=admin_id,
            note=note[:200], revoked=False,
        ))
    return key


def admin_revoke_key(key: str):
    with db.engine.begin() as c:
        c.execute(db.license_keys.update()
                  .where(db.license_keys.c.key == key).values(revoked=True))
        c.execute(db.license_activations.update()
                  .where(db.license_activations.c.key == key).values(revoked=True))


def admin_revoke_device(activation_id: int):
    with db.engine.begin() as c:
        c.execute(db.license_activations.update()
                  .where(db.license_activations.c.id == activation_id)
                  .values(revoked=True))


def admin_key_devices(key: str) -> list:
    la = db.license_activations.c
    with db.engine.connect() as c:
        rows = c.execute(
            sa.select(db.license_activations, db.users.c.email, db.users.c.name)
            .join(db.users, la.user_id == db.users.c.id, isouter=True)
            .where(la.key == key).order_by(la.activated_at.desc())
        ).all()
    return [{
        "id": m["id"], "user_id": m["user_id"],
        "email": m.get("email", ""), "name": m.get("name", ""),
        "hwid_short": m["hwid"][:8] + "...",
        "device_name": m.get("device_name", "Unknown"),
        "activated_at": m["activated_at"], "last_seen": m.get("last_seen"),
        "revoked": m["revoked"],
    } for m in (dict(r._mapping) for r in rows)]
