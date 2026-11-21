"""Email OTP for 2-step login verification."""
import hashlib, secrets, time, threading
from . import config, db
import sqlalchemy as sa

_otps: dict = {}  # {user_id: (otp_hash, expires_at, attempts)}
_lock = threading.Lock()
OTP_TTL = 120   # 2 minutes
OTP_MAX = 5

def _h(v): return hashlib.sha256(v.encode()).hexdigest()

def is_enabled(user_id: str) -> bool:
    with db.engine.connect() as c:
        row = c.execute(sa.select(db.totp_settings).where(
            db.totp_settings.c.user_id == user_id)).first()
        return bool(row and row.enabled)

def set_enabled(user_id: str, on: bool):
    with db.engine.begin() as c:
        exists = c.execute(sa.select(db.totp_settings.c.user_id).where(
            db.totp_settings.c.user_id == user_id)).first()
        if exists:
            c.execute(db.totp_settings.update().where(
                db.totp_settings.c.user_id == user_id).values(
                enabled=on, enabled_at=time.time() if on else None))
        else:
            c.execute(db.totp_settings.insert().values(
                user_id=user_id, enabled=on,
                enabled_at=time.time() if on else None))

def generate_and_send(user_id: str, email: str, purpose: str = "login") -> bool:
    otp = str(secrets.randbelow(90000000) + 10000000)
    with _lock:
        _otps[user_id] = (_h(otp), time.time() + OTP_TTL, 0)
    from . import mailer
    return mailer.send_otp(email, otp, purpose=purpose)

def verify(user_id: str, otp: str) -> bool:
    otp = otp.strip()
    with _lock:
        entry = _otps.get(user_id)
        if not entry: return False
        otp_hash, expires, attempts = entry
        if time.time() > expires:
            del _otps[user_id]; return False
        if attempts >= OTP_MAX:
            del _otps[user_id]; return False
        if _h(otp) != otp_hash:
            _otps[user_id] = (otp_hash, expires, attempts + 1)
            return False
        del _otps[user_id]
        return True

def is_trusted_device(user_id: str, token: str) -> bool:
    if not token: return False
    now = time.time()
    with db.engine.connect() as c:
        row = c.execute(sa.select(db.device_trusts).where(
            db.device_trusts.c.token_hash == _h(token),
            db.device_trusts.c.user_id == user_id,
            db.device_trusts.c.expires_at > now)).first()
    return bool(row)

def trust_device(user_id: str, device_name: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with db.engine.begin() as c:
        c.execute(db.device_trusts.insert().values(
            user_id=user_id,
            token_hash=_h(token),
            created_at=now,
            expires_at=now + 30 * 86400,
            device_name=device_name[:200]))
    return token

def revoke_all_trusted(user_id: str):
    with db.engine.begin() as c:
        c.execute(db.device_trusts.delete().where(
            db.device_trusts.c.user_id == user_id))
