"""Set isolated test configuration before any application module is imported."""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["APP_URL"] = "http://localhost:5173"
os.environ["SESSION_SECRET"] = "test-secret-with-at-least-32-characters"
os.environ.pop("VERCEL", None)
