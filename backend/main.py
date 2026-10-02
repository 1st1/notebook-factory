import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from uuid import uuid4

import anyio
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from vercel.headers import HeadersContext

import chat
import editor
import publication
from auth import require_owner
from auth import router as auth_router
from db import engine, initialize, notebooks, timestamp
from render import CONTENT_POLICY, new_notebook, render, validate

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
    source: str | None = Field(default=None, max_length=10 * 1024 * 1024)


async def get_notebook(id):
    async with engine.connect() as conn:
        row = (await conn.execute(select(notebooks).where(notebooks.c.id == id))).mappings().first()
    if row is None:
        raise HTTPException(404, "Notebook not found")
    return dict(row)


def public(row):
    return {
        key: row[key]
        for key in ("id", "title", "created_at", "updated_at", "revision", "render_url")
    }


@app.get("/api/notebooks")
async def list_notebooks():
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(
                    notebooks.c.id,
                    notebooks.c.title,
                    notebooks.c.created_at,
                    notebooks.c.updated_at,
                    notebooks.c.revision,
                    notebooks.c.render_url,
                ).order_by(notebooks.c.updated_at.desc())
            )
        ).mappings()
        return [public(row) for row in rows]


@app.post("/api/notebooks", dependencies=[Depends(require_owner)], status_code=201)
async def create_notebook(body: CreateNotebook):
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Enter a notebook title")
    source = new_notebook(title)
    id = str(uuid4())
    html = await anyio.to_thread.run_sync(render, source)
    render_url = await publication.upload(id, html)
    row = dict(
        id=id,
        title=title,
        source=source,
        published=source,
        published_html=html,
        render_url=render_url,
        created_at=timestamp(),
        updated_at=timestamp(),
        revision=1,
    )
    async with engine.begin() as conn:
        await conn.execute(notebooks.insert().values(**row))
    return public(row)


@app.get("/api/notebooks/{id}/render")
async def rendered(id: str):
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(
                    notebooks.c.published_html, notebooks.c.render_url, notebooks.c.revision
                ).where(notebooks.c.id == id)
            )
        ).first()
    if row is None:
        raise HTTPException(404, "Notebook not found")
    row = dict(row._mapping)
    html = row["published_html"]
    if html is None:
        # Legacy rows are rendered once. Never attach an old render to a newer publication.
        row = await get_notebook(id)
        html = await anyio.to_thread.run_sync(render, row["published"])
        async with engine.begin() as conn:
            await conn.execute(
                update(notebooks)
                .where(
                    notebooks.c.id == id,
                    notebooks.c.revision == row["revision"],
                    notebooks.c.published_html.is_(None),
                )
                .values(published_html=html)
            )
    if publication.enabled() and not row["render_url"]:
        url = await publication.upload(id, html)
        async with engine.begin() as conn:
            await conn.execute(
                update(notebooks)
                .where(
                    notebooks.c.id == id,
                    notebooks.c.revision == row["revision"],
                    notebooks.c.render_url.is_(None),
                )
                .values(render_url=url)
            )
    return HTMLResponse(
        html,
        headers={"Content-Security-Policy": "sandbox allow-scripts; " + CONTENT_POLICY},
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
        with anyio.CancelScope(shield=True):
            async with engine.begin() as conn:
                await conn.execute(
                    update(notebooks)
                    .where(notebooks.c.id == id, notebooks.c.claim == claim)
                    .values(claim=None, claim_until=0)
                )


@app.post("/api/notebooks/{id}/editor", dependencies=[Depends(require_owner)])
async def open_editor(id: str, request: Request):
    if "text/event-stream" not in request.headers.get("accept", ""):
        async with editor_lease(id) as claim:
            return await provision_editor(id, claim)
    await get_notebook(id)

    async def stream():
        events = asyncio.Queue()

        def report(kind, message):
            events.put_nowait({"type": kind, "message": message})

        async def provision():
            try:
                report("progress", "Checking your saved environment…")
                async with editor_lease(id) as claim:
                    result = await provision_editor(id, claim, report)
                events.put_nowait({"type": "ready", "editor": result})
            except HTTPException as error:
                report("error", error.detail)
            except Exception:
                log.exception("Editor setup stream failed")
                report("error", "Could not start the editor. Please retry.")

        task = asyncio.create_task(provision())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(events.get(), timeout=10)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield "data: " + json.dumps(event) + "\n\n"
                if event["type"] in {"ready", "error"}:
                    break
        finally:
            task.cancel()
            with anyio.CancelScope(shield=True):
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


async def provision_editor(id, claim, report=None):
    created = None
    retired = None
    generation = editor.generation()
    try:
        row = await get_notebook(id)
        if row["editor"]:
            old = json.loads(row["editor"])
            try:
                source = await editor.read(old)
                validate(source)
                if old.get("generation") == generation:
                    return old
                if report:
                    report("progress", "Updating the environment for this deployment…")
                # Back up the most recent Jupyter-saved draft before replacement.
                async with engine.begin() as conn:
                    await conn.execute(
                        update(notebooks)
                        .where(notebooks.c.id == id, notebooks.c.claim == claim)
                        .values(source=source)
                    )
                row["source"] = source
                retired = old
            except HTTPException as error:
                if error.status_code != 410:
                    raise
            except Exception:
                # Preserve the previous session on transient provider errors.
                raise HTTPException(502, "Could not reach the editor. Try again shortly.") from None
        created = (
            await editor.start(row["source"], report)
            if report
            else await editor.start(row["source"])
        )
        created = {**created, "generation": generation}
        async with engine.begin() as conn:
            result = await conn.execute(
                update(notebooks)
                .where(notebooks.c.id == id, notebooks.c.claim == claim)
                .values(editor=json.dumps(created))
            )
            if result.rowcount != 1:
                raise RuntimeError("Editor provisioning lease expired")
        if retired:
            await stop_closed_editor(retired)
        return created
    except HTTPException:
        raise
    except BaseException as error:
        log.exception("Could not start editor")
        if created:
            with anyio.CancelScope(shield=True):
                await editor.stop(created)
        if isinstance(error, asyncio.CancelledError):
            raise
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
async def save(id: str, body: EditorRequest, background_tasks: BackgroundTasks):
    async with editor_lease(id):
        result = await save_draft(id, body)
        if body.source is not None:
            _, current = await checked_editor(id, body.token)
            background_tasks.add_task(keep_editor_alive, current)
        return result


async def keep_editor_alive(current):
    try:
        await editor.keep_alive(current)
    except Exception:
        log.info("Sandbox unavailable after durable draft save", exc_info=True)


async def save_draft(id: str, body: EditorRequest, *, closing=False):
    row, current = await checked_editor(id, body.token)
    source = body.source
    if source is None:
        source = await editor.read(current, extend=False) if closing else await editor.read(current)
    validate(source)
    values = {"source": source}
    if body.publish:
        html = await anyio.to_thread.run_sync(render, source)
        values.update(
            published=source,
            published_html=html,
            render_url=await publication.upload(id, html),
            updated_at=timestamp(),
            revision=notebooks.c.revision + 1,
        )
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
async def close(id: str, body: EditorRequest, background_tasks: BackgroundTasks):
    async with editor_lease(id):
        row, current = await checked_editor(id, body.token)
        # Saving first means a failed persistence operation never destroys the draft.
        await save_draft(id, body, closing=True)
        async with engine.begin() as conn:
            await conn.execute(
                update(notebooks)
                .where(notebooks.c.id == id, notebooks.c.editor == row["editor"])
                .values(editor=None)
            )
        background_tasks.add_task(stop_closed_editor, current)
        return {"closed": True}


@app.post("/api/notebooks/{id}/delete", dependencies=[Depends(require_owner)])
async def delete_notebook(id: str, background_tasks: BackgroundTasks):
    async with editor_lease(id):
        row = await get_notebook(id)
        async with engine.begin() as conn:
            await conn.execute(delete(notebooks).where(notebooks.c.id == id))
        if row["editor"]:
            background_tasks.add_task(stop_closed_editor, json.loads(row["editor"]))
        background_tasks.add_task(delete_notebook_artifacts, id)
    return {"deleted": True}


async def delete_notebook_artifacts(id: str):
    try:
        await publication.remove(id)
    except Exception:
        log.exception("Could not remove published notebook artifacts for %s", id)


@app.post("/api/notebooks/{id}/discard", dependencies=[Depends(require_owner)])
async def discard(id: str, body: EditorRequest, background_tasks: BackgroundTasks):
    async with editor_lease(id):
        row, current = await checked_editor(id, body.token)
        async with engine.begin() as conn:
            await conn.execute(
                update(notebooks)
                .where(notebooks.c.id == id, notebooks.c.editor == row["editor"])
                .values(source=notebooks.c.published, editor=None)
            )
        background_tasks.add_task(stop_closed_editor, current)
        return {"closed": True, "discarded": True}


async def stop_closed_editor(current):
    try:
        await editor.stop(current)
    except Exception:
        # The draft is durable and the session detached; its timeout bounds cleanup failures.
        log.exception("Could not stop closed editor")


@app.get("/api/health")
async def health():
    return JSONResponse({"ok": True})


@app.post("/api/notebooks/{id}/chat", dependencies=[Depends(require_owner)])
async def notebook_chat(id: str, request: Request):
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "Chat history is too large. Start a new chat.")
    try:
        body = chat.ChatRequest.model_validate_json(raw)
        messages, _ = chat.ai.ui.ai_sdk.to_messages(body.messages)
    except ValueError:
        raise HTTPException(422, "Invalid chat messages") from None
    await checked_editor(id, body.token)
    return StreamingResponse(
        chat.stream(
            messages, body.messages[-1].id if body.messages[-1].role == "assistant" else None
        ),
        headers=chat.ai.ui.ai_sdk.UI_MESSAGE_STREAM_HEADERS,
    )


@app.post("/api/notebooks/{id}/chat-history", dependencies=[Depends(require_owner)])
async def load_chat_history(id: str, body: EditorRequest):
    row, _ = await checked_editor(id, body.token)
    return {"messages": json.loads(row["chat_history"] or "[]"), "revision": row["chat_revision"]}


@app.put("/api/notebooks/{id}/chat-history", dependencies=[Depends(require_owner)])
async def save_chat_history(id: str, request: Request):
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "Chat history is too large. Start a new chat.")
    try:
        body = chat.HistoryRequest.model_validate_json(raw)
    except ValueError:
        raise HTTPException(422, "Invalid chat history") from None
    row, _ = await checked_editor(id, body.token)
    history = json.dumps(chat.history_messages(body.messages))
    if len(history.encode()) > 1_000_000:
        raise HTTPException(413, "Chat history is too large. Start a new chat.")
    async with engine.begin() as conn:
        result = await conn.execute(
            update(notebooks)
            .where(
                notebooks.c.id == id,
                notebooks.c.editor == row["editor"],
                notebooks.c.chat_revision == body.revision,
            )
            .values(chat_history=history, chat_revision=body.revision + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(
                409, "Chat changed in another session. Reload saved chat before continuing."
            )
    return {"revision": body.revision + 1}
