"""GitHub identity enrollment and the application admission limit."""

import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import select, text, update

from config import APP_URL
from db import engine, timestamp, users

USER_LIMIT = 300


def sandbox_name(login: str, slot: int):
    slug = re.sub(r"[^a-z0-9-]", "-", login.lower())[:24]
    suffix = hashlib.sha256(f"{APP_URL}:{slot}".encode()).hexdigest()[:16]
    return f"nf-{slug}-{suffix}"


async def enroll(profile):
    github_id = profile.get("id")
    login = str(profile.get("login", "")).lower()
    if not isinstance(github_id, int) or github_id <= 0 or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,38}", login):
        raise HTTPException(401, "Invalid GitHub identity; sign in again")
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(734823110)"))
        else:
            await conn.execute(text("BEGIN IMMEDIATE"))
        rows = (await conn.execute(select(users))).mappings().all()
        existing = next((row for row in rows if row["github_id"] == github_id), None)
        # Only a GitHub-verified 1st1 identity may claim the legacy workspace.
        if existing is None and login == "1st1":
            existing = next((row for row in rows if row["id"] == 1 and row["github_id"] is None), None)
        avatar = f"https://avatars.githubusercontent.com/u/{github_id}?s=64"
        if existing is not None:
            # A username rename never changes runtime identity or notebook ownership.
            conflict = next((row for row in rows if row["login"] == login and row["id"] != existing["id"]), None)
            if conflict:
                raise HTTPException(409, "GitHub username conflicts with an existing account")
            await conn.execute(update(users).where(users.c.id == existing["id"]).values(
                github_id=github_id, login=login, avatar_url=avatar,
            ))
            return {**dict(existing), "github_id": github_id, "login": login, "avatar_url": avatar}
        if len(rows) >= USER_LIMIT:
            raise HTTPException(403, "Notebook Factory has reached its 300-user signup limit. Existing users can still sign in.")
        if any(row["login"] == login for row in rows):
            raise HTTPException(409, "GitHub username conflicts with an existing account")
        used = {row["id"] for row in rows}
        slot = next(i for i in range(1, 501) if i not in used)
        account = dict(id=slot, github_id=github_id, login=login, avatar_url=avatar,
                       sandbox_name=sandbox_name(login, slot), created_at=timestamp())
        await conn.execute(users.insert().values(**account))
        return account


async def from_session(profile):
    """Resolve stable identity without taking the signup lock on every API call."""
    github_id = profile.get("id")
    if not isinstance(github_id, int) or github_id <= 0:
        raise HTTPException(401, "Invalid GitHub identity; sign in again")
    async with engine.connect() as conn:
        row = (await conn.execute(select(users).where(users.c.github_id == github_id))).mappings().first()
    return dict(row) if row else await enroll(profile)
