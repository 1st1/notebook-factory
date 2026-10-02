import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
APP_URL = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
SECRET = os.getenv("SESSION_SECRET", "")
PRODUCTION = bool(os.getenv("VERCEL")) and os.getenv("VERCEL_ENV") != "development"
if PRODUCTION and (len(SECRET) < 32 or not APP_URL.startswith("https://")):
    raise RuntimeError("Set SESSION_SECRET (32+ characters) and an HTTPS APP_URL")
# A deterministic local-only key keeps sessions stable during reloads.
SECRET = SECRET or "local-development-only-not-for-production"
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    if PRODUCTION:
        raise RuntimeError("DATABASE_URL is required on Vercel")
    DATABASE_URL = "sqlite+aiosqlite:///" + str(Path(__file__).with_name("notebooks.db"))
if DATABASE_URL.startswith(("postgres://", "postgresql://")):
    DATABASE_URL = "postgresql+asyncpg://" + DATABASE_URL.split("://", 1)[1]
    url = urlsplit(DATABASE_URL)
    query = dict(parse_qsl(url.query))
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")
    # libpq-only option in Neon URLs; asyncpg negotiates SCRAM itself.
    query.pop("channel_binding", None)
    DATABASE_URL = urlunsplit(url._replace(query=urlencode(query)))
if PRODUCTION and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise RuntimeError("Use a durable Postgres DATABASE_URL on Vercel")
MAX_BYTES = 10 * 1024 * 1024
