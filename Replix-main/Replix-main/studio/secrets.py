"""Replix Secrets Manager — fetches encrypted secrets from Supabase vault at startup.

Secrets are stored in a `app_secrets` table in Supabase (encrypted at rest).
They are loaded once at startup into memory — never written to disk.

To add a secret:
  python -m studio.secrets set smtp_password "your-app-password"
  python -m studio.secrets set github_pat "ghp_..."
  python -m studio.secrets set discord_server_logs "https://discord.com/..."
  python -m studio.secrets list
"""
import os
import sys
import time
import threading

_cache: dict = {}
_loaded = False
_lock = threading.Lock()


def _get_conn():
    """Get a direct DB connection (not pooled — used only at startup)."""
    import sqlalchemy as sa
    from . import config
    url = config.DATABASE_URL
    _sqlite = url.startswith("sqlite")
    connect_args = {"timeout": 10} if _sqlite else {}
    engine = sa.create_engine(url, pool_pre_ping=not _sqlite, future=True,
                               connect_args=connect_args)
    return engine


def _ensure_table(engine):
    import sqlalchemy as sa
    meta = sa.MetaData()
    table = sa.Table(
        "app_secrets", meta,
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Float, nullable=False),
    )
    meta.create_all(engine, checkfirst=True)
    return table


def load_all() -> dict:
    """Load all secrets from Supabase into memory. Called once at startup."""
    global _loaded, _cache
    with _lock:
        if _loaded:
            return _cache
        try:
            import sqlalchemy as sa
            engine = _get_conn()
            table = _ensure_table(engine)
            with engine.connect() as c:
                rows = c.execute(sa.select(table)).fetchall()
            _cache = {r[0]: r[1] for r in rows}
            _loaded = True
            print(f"[Replix] Loaded {len(_cache)} secrets from Supabase vault", flush=True)
        except Exception as e:
            print(f"[Replix] Warning: could not load secrets from Supabase: {e}", flush=True)
            _loaded = True  # don't retry on every request
        return _cache


def get(key: str, default: str = "") -> str:
    """Get a secret by key. Falls back to env var, then default."""
    if not _loaded:
        load_all()
    # Priority: env var > vault > default
    env_key = key.upper().replace("-", "_")
    env_val = os.environ.get(env_key, "")
    if env_val:
        return env_val
    return _cache.get(key, default)


def set_secret(key: str, value: str):
    """Store or update a secret in Supabase vault."""
    import sqlalchemy as sa
    engine = _get_conn()
    table = _ensure_table(engine)
    with engine.begin() as c:
        exists = c.execute(
            sa.select(table.c.key).where(table.c.key == key)).first()
        if exists:
            c.execute(table.update().where(table.c.key == key).values(
                value=value, updated_at=time.time()))
        else:
            c.execute(table.insert().values(
                key=key, value=value, updated_at=time.time()))
    # Update in-memory cache
    with _lock:
        _cache[key] = value
    print(f"[Replix] Secret '{key}' saved to Supabase vault.", flush=True)


def delete_secret(key: str):
    import sqlalchemy as sa
    engine = _get_conn()
    table = _ensure_table(engine)
    with engine.begin() as c:
        c.execute(table.delete().where(table.c.key == key))
    with _lock:
        _cache.pop(key, None)


def inject_to_env():
    """Inject vault secrets into os.environ so existing config.py picks them up.
    Called at app startup BEFORE config reads env vars."""
    secrets = load_all()
    mapping = {
        # vault key → env var name
        "smtp_password":        "REPLIX_SMTP_PASSWORD",
        "github_pat":           "REPLIX_GITHUB_PAT",
        "discord_server_logs":  "REPLIX_DISCORD_SERVER_LOGS",
        "discord_error_logs":   "REPLIX_DISCORD_ERROR_LOGS",
        "discord_other_logs":   "REPLIX_DISCORD_OTHER_LOGS",
        "supabase_service_key": "REPLIX_SUPABASE_SERVICE_KEY",
        "admin_path":           "REPLIX_ADMIN_PATH",
        "youtube_cookies":      "REPLIX_YT_COOKIES",
    }
    injected = 0
    for secret_key, env_key in mapping.items():
        if secret_key in secrets and not os.environ.get(env_key):
            os.environ[env_key] = secrets[secret_key]
            injected += 1
    if injected:
        print(f"[Replix] Injected {injected} secrets from vault into config", flush=True)


# ---------------------------------------------------------------- CLI
def _cli():
    argv = sys.argv[1:]
    if not argv or argv[0] == "list":
        load_all()
        if not _cache:
            print("No secrets stored yet.")
        for k, v in sorted(_cache.items()):
            hidden = v[:4] + "***" + v[-4:] if len(v) > 10 else "***"
            print(f"  {k:<30} {hidden}")
        return

    if len(argv) == 3 and argv[0] == "set":
        set_secret(argv[1], argv[2])
        return

    if len(argv) == 2 and argv[0] == "delete":
        delete_secret(argv[1])
        print(f"Deleted '{argv[1]}'")
        return

    print(__doc__)


if __name__ == "__main__":
    _cli()
