"""The database: accounts, sign-in sessions, notifications and the record of AI use.

PostgreSQL on a server (DATABASE_URL=postgresql+psycopg://...). With no DATABASE_URL it uses a SQLite file,
which is fine for one machine."""
import time

import sqlalchemy as sa

from . import config

_SQLITE = config.DATABASE_URL.startswith("sqlite")
engine = sa.create_engine(config.DATABASE_URL, pool_pre_ping=not _SQLITE, future=True, pool_size=20, max_overflow=40,
                          **({"connect_args": {"timeout": 30}} if _SQLITE else {}))

if _SQLITE:
    @sa.event.listens_for(engine, "connect")
    def _fast_sqlite(conn, _record):
        # WAL: people reading are never held up by someone writing. NORMAL: safe against crashes of the app,
        # without waiting for the disk on every single write.
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
meta = sa.MetaData()

users = sa.Table(
    "users", meta,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("email", sa.String(254), nullable=False, unique=True),          # always lower case
    sa.Column("name", sa.String(120), nullable=False, server_default=""),
    sa.Column("password_hash", sa.String(300)),                               # empty for Google-only accounts
    sa.Column("google_sub", sa.String(64), unique=True),
    sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("last_seen", sa.Float),
)
sessions = sa.Table(
    "sessions", meta,
    sa.Column("token_hash", sa.String(64), primary_key=True),                 # sha256 of the cookie; the cookie itself is never stored
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("expires_at", sa.Float, nullable=False),
    sa.Column("ip", sa.String(64)),
    sa.Column("agent", sa.String(300)),
)
usage = sa.Table(                                                             # one row per AI call
    "usage", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("t", sa.Float, nullable=False),
    sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),   # text sent to the AI
    sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),  # text it wrote back
    sa.Column("purpose", sa.String(60), nullable=False),
    sa.Column("creator", sa.String(80)),
    sa.Column("place", sa.String(200)),
    sa.Index("usage_user_t", "user_id", "t"),
)


email_ok = sa.Table(                                                          # addresses proven to belong to the account
    "email_ok", meta,
    sa.Column("user_id", sa.String(40), primary_key=True),                    # "_existing" marks that older accounts were counted
    sa.Column("verified_at", sa.Float, nullable=False),
)
email_tokens = sa.Table(                                                      # one-time links: verify an email, reset a password
    "email_tokens", meta,
    sa.Column("token_hash", sa.String(64), primary_key=True),                 # sha256 of the link token; the token itself is never stored
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("purpose", sa.String(10), nullable=False),                      # verify | reset
    sa.Column("expires_at", sa.Float, nullable=False),
    sa.Column("used_at", sa.Float),
)


feedback = sa.Table(                                                          # bug reports and ideas, read by admins
    "feedback", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="SET NULL")),
    sa.Column("t", sa.Float, nullable=False, index=True),
    sa.Column("kind", sa.String(10), nullable=False),                         # bug | idea | other
    sa.Column("message", sa.Text, nullable=False),
    sa.Column("page", sa.String(200), nullable=False, server_default=""),     # where in the app they were
    sa.Column("context", sa.String(1000), nullable=False, server_default=""), # e.g. the error they were looking at
    sa.Column("status", sa.String(10), nullable=False, server_default="new", index=True),  # new | seen | done
    sa.Column("updated_at", sa.Float, nullable=False),
)
notices = sa.Table(                                                           # the bell: things worth telling someone about
    "notices", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("t", sa.Float, nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),                         # live | clips | post | account | feedback
    sa.Column("title", sa.String(160), nullable=False),
    sa.Column("body", sa.String(400), nullable=False, server_default=""),
    sa.Column("link", sa.String(200), nullable=False, server_default=""),
    sa.Column("ref", sa.String(80)),                                          # set when it must only be sent once
    sa.Column("read_at", sa.Float),
    sa.Index("notices_user_t", "user_id", "t"),
)


admin_log = sa.Table(                                                         # what admins did, never edited
    "admin_log", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("t", sa.Float, nullable=False, index=True),
    sa.Column("admin_id", sa.String(40), nullable=False),
    sa.Column("action", sa.String(30), nullable=False),                       # disable | enable | delete | role:admin | role:user
    sa.Column("target_id", sa.String(40)),
    sa.Column("detail", sa.String(300), nullable=False, server_default=""),
)

totp_settings = sa.Table(
    "totp_settings", meta,
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("enabled_at", sa.Float),
)

device_trusts = sa.Table(
    "device_trusts", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("expires_at", sa.Float, nullable=False),
    sa.Column("device_name", sa.String(200), nullable=False, server_default=""),
)

license_keys = sa.Table(
    "license_keys", meta,
    sa.Column("key", sa.String(50), primary_key=True),
    sa.Column("plan", sa.String(20), nullable=False, server_default="starter"),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("expires_at", sa.Float),
    sa.Column("max_devices", sa.Integer, nullable=False, server_default="1"),
    sa.Column("created_by", sa.String(40)),
    sa.Column("note", sa.String(200), nullable=False, server_default=""),
    sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
)

license_activations = sa.Table(
    "license_activations", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("key", sa.String(50), sa.ForeignKey("license_keys.key", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("hwid", sa.String(64), nullable=False),
    sa.Column("activated_at", sa.Float, nullable=False),
    sa.Column("last_seen", sa.Float),
    sa.Column("device_name", sa.String(200), nullable=False, server_default=""),
    sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Index("lic_act_user", "user_id"),
    sa.Index("lic_act_hwid", "hwid"),
)

user_data = sa.Table(
    "user_data", meta,
    sa.Column("user_id", sa.String(40), nullable=False),
    sa.Column("category", sa.String(40), nullable=False),
    sa.Column("data", sa.Text, nullable=False),
    sa.Column("updated_at", sa.Float, nullable=False),
    sa.PrimaryKeyConstraint("user_id", "category"),
)


def get_user_data(user_id: str, category: str):
    """Fetch stored JSON data for user and category from DB, or None."""
    try:
        import json
        with engine.connect() as conn:
            row = conn.execute(
                sa.select(user_data.c.data).where(
                    user_data.c.user_id == user_id,
                    user_data.c.category == category
                )
            ).first()
            if row and row[0]:
                return json.loads(row[0])
    except Exception:
        pass
    return None


def set_user_data(user_id: str, category: str, data) -> bool:
    """Store JSON data for user and category in DB."""
    try:
        import json
        payload = json.dumps(data)
        now_ts = time.time()
        with engine.begin() as conn:
            exists = conn.execute(
                sa.select(user_data.c.user_id).where(
                    user_data.c.user_id == user_id,
                    user_data.c.category == category
                )
            ).first()
            if exists:
                conn.execute(
                    user_data.update().where(
                        user_data.c.user_id == user_id,
                        user_data.c.category == category
                    ).values(data=payload, updated_at=now_ts)
                )
            else:
                conn.execute(
                    user_data.insert().values(
                        user_id=user_id,
                        category=category,
                        data=payload,
                        updated_at=now_ts
                    )
                )
        return True
    except Exception:
        return False


def init():
    meta.create_all(engine, checkfirst=True)


def now() -> float:
    return time.time()
