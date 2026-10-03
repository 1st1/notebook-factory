"""Deployment database aliases must work without a local dotenv file."""
import runpy
import sys
import types
from pathlib import Path


# @lat: [[deployment#Environment configuration]]
def test_supabase_integration_url(monkeypatch):
    monkeypatch.setitem(sys.modules, 'dotenv', types.SimpleNamespace(load_dotenv=lambda *_: None))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_ENV', 'production')
    monkeypatch.setenv('SESSION_SECRET', 'x' * 32)
    monkeypatch.setenv('APP_URL', 'https://example.com')
    monkeypatch.setenv('POSTGRES_URL', 'postgres://user:pass@aws-0-us-west-1.pooler.supabase.com:6543/postgres?sslmode=require&supa=base-pooler.x')
    config = runpy.run_path(str(Path(__file__).parents[1] / 'config.py'))
    assert config['DATABASE_URL'] == 'postgresql+asyncpg://user:pass@aws-0-us-west-1.pooler.supabase.com:5432/postgres?ssl=require'
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@custom.example:5432/app')
    config = runpy.run_path(str(Path(__file__).parents[1] / 'config.py'))
    assert config['DATABASE_URL'] == 'postgresql+asyncpg://user:pass@custom.example:5432/app'
