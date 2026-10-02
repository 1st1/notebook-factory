"""Cross-function coordination for the per-user shared notebook runtimes."""

import json
import secrets
from contextlib import asynccontextmanager

import anyio
from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from db import engine, runtimes, timestamp


@asynccontextmanager
async def runtime_lease(key):
    # Insert once without relying on a process-local lock or a particular SQL dialect.
    async with engine.connect() as conn:
        exists = await conn.scalar(select(runtimes.c.id).where(runtimes.c.id == key))
    if exists is None:
        try:
            async with engine.begin() as conn:
                await conn.execute(runtimes.insert().values(id=key, claim_until=0))
        except IntegrityError:
            pass
    claim = secrets.token_hex(16)
    deadline = anyio.current_time() + 150
    while True:
        async with engine.begin() as conn:
            result = await conn.execute(update(runtimes).where(
                runtimes.c.id == key,
                or_(runtimes.c.claim_until < timestamp(), runtimes.c.claim.is_(None)),
            ).values(claim=claim, claim_until=timestamp() + 240))
        if result.rowcount == 1:
            break
        if anyio.current_time() >= deadline:
            raise HTTPException(409, "The shared runtime is starting. Please retry shortly.")
        await anyio.sleep(0.25)
    try:
        yield claim
    finally:
        with anyio.CancelScope(shield=True):
            async with engine.begin() as conn:
                await conn.execute(update(runtimes).where(
                    runtimes.c.id == key, runtimes.c.claim == claim,
                ).values(claim=None, claim_until=0))


async def load_runtime(key):
    async with engine.connect() as conn:
        state = await conn.scalar(select(runtimes.c.state).where(runtimes.c.id == key))
    return json.loads(state) if state else None


async def store_runtime(key, claim, state):
    async with engine.begin() as conn:
        result = await conn.execute(update(runtimes).where(
            runtimes.c.id == key, runtimes.c.claim == claim,
        ).values(state=json.dumps(state)))
    if result.rowcount != 1:
        raise RuntimeError("Shared runtime lease expired")
