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
    assert config['DATABASE_URL'] == 'postgresql+psycopg://user:pass@aws-0-us-west-1.pooler.supabase.com:6543/postgres?sslmode=require'
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@custom.example:5432/app')
    config = runpy.run_path(str(Path(__file__).parents[1] / 'config.py'))
    assert config['DATABASE_URL'] == 'postgresql+psycopg://user:pass@custom.example:5432/app'


# @lat: [[deployment#Environment configuration]]
async def test_postgres_releases_connections_and_disables_preparation(monkeypatch):
    import pytest
    from sqlalchemy import event
    from sqlalchemy.pool import NullPool

    monkeypatch.setitem(sys.modules, 'config', types.SimpleNamespace(
        DATABASE_URL='postgresql+psycopg://user:pass@localhost:6543/postgres?sslmode=require',
    ))
    db = runpy.run_path(str(Path(__file__).parents[1] / 'db.py'))
    engine = db['engine']
    assert isinstance(engine.pool, NullPool)
    captured = {}

    @event.listens_for(engine.sync_engine, 'do_connect')
    def capture(dialect, record, args, kwargs):
        captured.update(kwargs)
        raise RuntimeError('connection intercepted')

    with pytest.raises(RuntimeError, match='connection intercepted'):
        async with engine.connect():
            pass
    assert captured['prepare_threshold'] is None
    assert captured['sslnegotiation'] == 'postgres'
    assert captured['port'] == 6543
    assert captured['sslmode'] == 'require'
    await engine.dispose()
