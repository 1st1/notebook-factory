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
            dict(id=i, vercel_id=str(i), login=f"user-{i}", sandbox_name=f"nf-{i}", created_at=0)
            for i in range(1, count + 1)
        ])


# @lat: [[architecture#Multi-user isolation tests]]
async def test_signup_cap_is_atomic_and_existing_users_can_return(account_db):
    await seed(account_db, 299)
    results = await asyncio.gather(*[
        accounts.enroll({"sub": str(1000 + i), "preferred_username": f"new-{i}"}) for i in range(6)
    ], return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert all(isinstance(result, dict) or isinstance(result, HTTPException) and result.status_code == 403 for result in results)
    async with account_db.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(db.users)) == 300
    renamed = await accounts.enroll({"sub": "1", "preferred_username": "renamed-user"})
    assert renamed["id"] == 1 and renamed["sandbox_name"] == "nf-1"


async def test_database_hard_limit_cannot_exceed_500_rows(account_db):
    await seed(account_db, 500)
    for slot in (0, 501, 1):
        with pytest.raises(IntegrityError):
            async with account_db.begin() as conn:
                await conn.execute(db.users.insert().values(
                    id=slot, vercel_id="10001", login="overflow", sandbox_name="nf-overflow", created_at=0,
                ))
    async with account_db.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(db.users)) == 500


async def test_identity_is_stable_and_username_is_not_ownership(account_db):
    alice = await accounts.enroll({"sub": "alice-id", "preferred_username": "Alice"})
    other = await accounts.enroll({"sub": "other-id", "preferred_username": "Alice"})
    assert alice["id"] != other["id"] and alice["login"] != other["login"]
    renamed = await accounts.enroll({"sub": "alice-id", "preferred_username": "New-Alice"})
    assert renamed["id"] == alice["id"]
    assert renamed["sandbox_name"] == alice["sandbox_name"]
    current = await accounts.from_session({"provider": "vercel", "sub": "alice-id"})
    assert current["login"] == "new-alice"
    with pytest.raises(HTTPException):
        await accounts.from_session({"provider": "github", "sub": "alice-id"})


async def test_fresh_database_has_no_reserved_user(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "fresh.db"))
    monkeypatch.setattr(db, "engine", engine)
    await db.initialize()
    await db.initialize()
    async with engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(db.users)) == 0
        assert await conn.scalar(select(func.count()).select_from(db.notebooks)) == 0
    await engine.dispose()
