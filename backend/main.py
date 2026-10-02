import json
import logging
import secrets
from contextlib import asynccontextmanager
from uuid import uuid4

import anyio
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update
from vercel.headers import HeadersContext

import editor
from auth import require_owner
from auth import router as auth_router
from db import engine, initialize, notebooks, timestamp
from render import new_notebook, render, validate

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    await initialize()
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)


@app.middleware("http")
async def headers(request, call_next):
    with HeadersContext(dict(request.headers)).use():
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


class CreateNotebook(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class EditorRequest(BaseModel):
    token: str
    publish: bool = False


async def get_notebook(id):
    async with engine.connect() as conn:
        row = (await conn.execute(select(notebooks).where(notebooks.c.id == id))).mappings().first()
    if row is None:
        raise HTTPException(404, "Notebook not found")
    return dict(row)


def public(row):
    return {key: row[key] for key in ("id", "title", "created_at", "updated_at", "revision")}


@app.get("/api/notebooks")
async def list_notebooks():
    async with engine.connect() as conn:
        rows = (
            await conn.execute(select(notebooks).order_by(notebooks.c.updated_at.desc()))
        ).mappings()
        return [public(row) for row in rows]


@app.post("/api/notebooks", dependencies=[Depends(require_owner)], status_code=201)
async def create_notebook(body: CreateNotebook):
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Enter a notebook title")
    source = new_notebook(title)
    row = dict(
        id=str(uuid4()),
        title=title,
        source=source,
        published=source,
        created_at=timestamp(),
        updated_at=timestamp(),
        revision=1,
    )
    async with engine.begin() as conn:
        await conn.execute(notebooks.insert().values(**row))
    return public(row)


@app.get("/api/notebooks/{id}/render")
async def rendered(id: str):
    row = await get_notebook(id)
    html = await anyio.to_thread.run_sync(render, row["published"])
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; style-src 'unsafe-inline' https:; img-src data: https:; font-src data: https:; connect-src 'none'; frame-src 'none'"
        },
    )


@app.get("/api/notebooks/{id}/download")
async def download(id: str):
    row = await get_notebook(id)
    return Response(
        row["published"],
        media_type="application/x-ipynb+json",
        headers={"Content-Disposition": f'attachment; filename="{id}.ipynb"'},
    )


@asynccontextmanager
async def editor_lease(id):
    await get_notebook(id)
    # Atomic lease serializes mutations across Vercel function instances.
    claim = secrets.token_hex(16)
    async with engine.begin() as conn:
        result = await conn.execute(
            update(notebooks)
            .where(
                notebooks.c.id == id,
                or_(
                    notebooks.c.claim_until < timestamp(),
                    notebooks.c.claim_until.is_(None),
                ),
            )
            .values(claim=claim, claim_until=timestamp() + 300)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "An editor operation is in progress; try again shortly")
    try:
        yield claim
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                update(notebooks)
                .where(notebooks.c.id == id, notebooks.c.claim == claim)
                .values(claim=None, claim_until=0)
            )


@app.post("/api/notebooks/{id}/editor", dependencies=[Depends(require_owner)])
async def open_editor(id: str):
    async with editor_lease(id) as claim:
        return await provision_editor(id, claim)


async def provision_editor(id, claim):
    created = None
    try:
        row = await get_notebook(id)
        if row["editor"]:
            old = json.loads(row["editor"])
            try:
                source = await editor.read(old)
                validate(source)
                return old
            except HTTPException as error:
                if error.status_code != 410:
                    raise
            except Exception:
                # Preserve the previous session on transient provider errors.
                raise HTTPException(502, "Could not reach the editor. Try again shortly.") from None
        created = await editor.start(row["source"])
        async with engine.begin() as conn:
            result = await conn.execute(
                update(notebooks)
                .where(notebooks.c.id == id, notebooks.c.claim == claim)
                .values(editor=json.dumps(created))
            )
            if result.rowcount != 1:
                raise RuntimeError("Editor provisioning lease expired")
        return created
    except HTTPException:
        raise
    except Exception:
        log.exception("Could not start editor")
        if created:
            await editor.stop(created)
        raise HTTPException(
            502, "Could not start Jupyter. Check Sandbox configuration and retry."
        ) from None


async def checked_editor(id, token):
    row = await get_notebook(id)
    current = json.loads(row["editor"]) if row["editor"] else None
    if not current or not secrets.compare_digest(current["token"], token):
        raise HTTPException(409, "This editor session is no longer active. Reopen the editor.")
    return row, current


@app.post("/api/notebooks/{id}/save", dependencies=[Depends(require_owner)])
async def save(id: str, body: EditorRequest):
    async with editor_lease(id):
        return await save_draft(id, body)


async def save_draft(id: str, body: EditorRequest):
    row, current = await checked_editor(id, body.token)
    source = await editor.read(current)
    validate(source)
    values = {"source": source}
    if body.publish:
        values.update(published=source, updated_at=timestamp(), revision=notebooks.c.revision + 1)
    async with engine.begin() as conn:
        result = await conn.execute(
            update(notebooks)
            .where(notebooks.c.id == id, notebooks.c.editor == row["editor"])
            .values(**values)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Editor changed while saving; retry")
    return {"saved_at": timestamp(), "published": body.publish}


@app.post("/api/notebooks/{id}/close", dependencies=[Depends(require_owner)])
async def close(id: str, body: EditorRequest):
    async with editor_lease(id):
        row, current = await checked_editor(id, body.token)
        # Saving first means a failed persistence operation never destroys the draft.
        await save_draft(id, body)
        await editor.stop(current)
        async with engine.begin() as conn:
            await conn.execute(
                update(notebooks)
                .where(notebooks.c.id == id, notebooks.c.editor == row["editor"])
                .values(editor=None)
            )
        return {"closed": True}


@app.get("/api/health")
async def health():
    return JSONResponse({"ok": True})
