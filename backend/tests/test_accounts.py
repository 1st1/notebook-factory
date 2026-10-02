import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

import accounts
import db


@pytest.fixture
async def account_db(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "users.db"))
    async with engine.begin() as conn:
        await conn.run_sync(db.users.create)
    monkeypatch.setattr(accounts, "engine", engine)
    yield engine
    await engine.dispose()


async def seed(engine, count):
    async with engine.begin() as conn:
        await conn.execute(db.users.insert(), [
            dict(id=i, github_id=i, login=f"user-{i}", sandbox_name=f"nf-{i}", created_at=0)
            for i in range(1, count + 1)
        ])


# @lat: [[architecture#Multi-user isolation tests]]
async def test_signup_cap_is_atomic_and_existing_users_can_return(account_db):
    await seed(account_db, 299)
    results = await asyncio.gather(*[
        accounts.enroll({"id": 1000 + i, "login": f"new-{i}"}) for i in range(6)
    ], return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert all(isinstance(result, dict) or isinstance(result, HTTPException) and result.status_code == 403 for result in results)
    async with account_db.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(db.users)) == 300
    renamed = await accounts.enroll({"id": 1, "login": "renamed-user"})
    assert renamed["id"] == 1 and renamed["sandbox_name"] == "nf-1"


async def test_database_hard_limit_cannot_exceed_500_rows(account_db):
    await seed(account_db, 500)
    for slot in (0, 501, 1):
        with pytest.raises(IntegrityError):
            async with account_db.begin() as conn:
                await conn.execute(db.users.insert().values(
                    id=slot, github_id=10001, login="overflow", sandbox_name="nf-overflow", created_at=0,
                ))
    async with account_db.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(db.users)) == 500


async def test_legacy_account_claim_and_username_identity(account_db):
    async with account_db.begin() as conn:
        await conn.execute(db.users.insert().values(
            id=1, login="1st1", sandbox_name=accounts.sandbox_name("1st1", 1), created_at=0,
        ))
    alice = await accounts.enroll({"id": 101, "login": "Alice"})
    assert alice["id"] == 2
    original = await accounts.enroll({"id": 202, "login": "1st1"})
    assert original["id"] == 1
    renamed = await accounts.enroll({"id": 101, "login": "Alice-New"})
    assert renamed["id"] == alice["id"]
    assert renamed["sandbox_name"] == alice["sandbox_name"]
    stale_session = await accounts.from_session({"id": 101, "login": "Alice"})
    assert stale_session["login"] == "alice-new"
    with pytest.raises(HTTPException):
        await accounts.enroll({"id": 303, "login": "1st1"})
    assert alice["sandbox_name"] != original["sandbox_name"]
    assert alice["sandbox_name"].startswith("nf-alice-")


async def test_legacy_notebooks_migrate_to_original_owner(tmp_path, monkeypatch):
    from sqlalchemy import text
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "legacy.db"))
    monkeypatch.setattr(db, "engine", engine)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE notebooks (id TEXT PRIMARY KEY, title TEXT, source TEXT, published TEXT, created_at INTEGER, updated_at INTEGER, revision INTEGER, editor TEXT, claim TEXT, claim_until INTEGER)"))
        await conn.execute(text("INSERT INTO notebooks (id, title, source, published, revision) VALUES ('old', 'Original', '{}', '{}', 1)"))
    await db.initialize()
    await db.initialize()
    async with engine.connect() as conn:
        notebook = (await conn.execute(select(db.notebooks))).mappings().one()
        owner = (await conn.execute(select(db.users))).mappings().one()
        assert notebook["owner_id"] == owner["id"] == 1
        assert owner["login"] == "1st1"
    await engine.dispose()
