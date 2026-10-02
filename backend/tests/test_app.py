import os
import tempfile
from unittest.mock import AsyncMock

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["APP_URL"] = "http://localhost:5173"
os.environ["SESSION_SECRET"] = "test-secret-with-at-least-32-characters"
os.environ.pop("VERCEL", None)

import pytest
from fastapi.testclient import TestClient

import main
from auth import COOKIE, signer
from render import new_notebook


@pytest.fixture
def client():
    with TestClient(main.app) as client:
        yield client


def authenticate(client, login="1st1"):
    client.cookies.set(COOKIE, signer.dumps({"login": login, "id": 1}, salt="session"))
    client.headers["origin"] = "http://localhost:5173"


def create(client):
    authenticate(client)
    response = client.post("/api/notebooks", json={"title": "A notebook"})
    assert response.status_code == 201
    return response.json()["id"]


# @lat: [[architecture#Authorization tests]]
@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/notebooks", {"title": "Forbidden"}),
        ("/api/notebooks/missing/editor", {}),
        ("/api/notebooks/missing/save", {"token": "x"}),
        ("/api/notebooks/missing/close", {"token": "x"}),
        ("/api/notebooks/missing/discard", {"token": "x"}),
        ("/api/notebooks/missing/delete", {}),
        ("/api/notebooks/missing/rename", {"token": "x", "title": "New title"}),
        ("/api/notebooks/missing/chat", {"token": "x", "messages": []}),
    ],
)
def test_mutations_require_owner_and_origin(client, path, body):
    assert client.post(path, json=body).status_code == 401
    authenticate(client, "someone-else")
    assert client.post(path, json=body).status_code == 403
    authenticate(client)
    client.headers["origin"] = "https://attacker.example"
    assert client.post(path, json=body).status_code == 403


def test_invalid_sessions_and_oauth_state(client):
    client.cookies.set(COOKIE, "forged")
    assert client.get("/api/auth/me").json()["can_edit"] is False
    assert client.get("/api/auth/callback?code=stolen&state=forged").status_code == 400


# @lat: [[architecture#Persistence tests]]
def test_drafts_publish_close_and_reopen(client, monkeypatch):
    id = create(client)
    first = {
        "generation": main.editor.generation(),
        "name": "sandbox-a",
        "url": "https://example.test/secret/doc/tree/notebook.ipynb",
        "token": "secret",
    }
    start = AsyncMock(return_value=first)
    read = AsyncMock(return_value=new_notebook("Unpublished changes"))
    stop = AsyncMock()
    monkeypatch.setattr(main.editor, "start", start)
    monkeypatch.setattr(main.editor, "read", read)
    monkeypatch.setattr(main.editor, "stop", stop)
    assert client.post(f"/api/notebooks/{id}/editor", json={}).json() == first
    assert client.post(f"/api/notebooks/{id}/editor", json={}).json() == first
    assert start.await_count == 1
    assert client.post(f"/api/notebooks/{id}/save", json={"token": "stale"}).status_code == 409
    assert client.post(f"/api/notebooks/{id}/save", json={"token": "secret"}).status_code == 200
    assert "Unpublished changes" not in client.get(f"/api/notebooks/{id}/download").text
    assert (
        client.post(
            f"/api/notebooks/{id}/save", json={"token": "secret", "publish": True}
        ).status_code
        == 200
    )
    assert "Unpublished changes" in client.get(f"/api/notebooks/{id}/download").text
    assert client.post(f"/api/notebooks/{id}/close", json={"token": "secret"}).status_code == 200
    stop.assert_awaited_once()
    assert client.post(f"/api/notebooks/{id}/editor", json={}).status_code == 200
    assert "Unpublished changes" in start.call_args.args[0]
    client.cookies.clear()
    listing = client.get("/api/notebooks").json()
    assert all("editor" not in item and "source" not in item for item in listing)
    html = client.get(f"/api/notebooks/{id}/render")
    assert html.status_code == 200 and "Unpublished changes" in html.text
    assert "sandbox allow-scripts;" in html.headers["content-security-policy"]
    assert "secret" not in html.text


def test_failed_save_does_not_stop_editor(client, monkeypatch):
    id = create(client)
    monkeypatch.setattr(
        main.editor,
        "start",
        AsyncMock(return_value={"name": "a", "token": "t", "url": "https://example.test"}),
    )
    monkeypatch.setattr(main.editor, "read", AsyncMock(return_value="not a notebook"))
    stop = AsyncMock()
    monkeypatch.setattr(main.editor, "stop", stop)
    client.post(f"/api/notebooks/{id}/editor", json={})
    assert client.post(f"/api/notebooks/{id}/close", json={"token": "t"}).status_code == 422
    stop.assert_not_awaited()


def test_startup_failure_releases_lease(client, monkeypatch):
    id = create(client)
    start = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    monkeypatch.setattr(main.editor, "start", start)
    for _ in range(2):
        assert client.post(f"/api/notebooks/{id}/editor", json={}).status_code == 502
    assert start.await_count == 2


def test_blank_title(client):
    authenticate(client)
    assert client.post("/api/notebooks", json={"title": "  "}).status_code == 422


def test_expired_editor_restores_draft(client, monkeypatch):
    id = create(client)
    monkeypatch.setattr(
        main.editor,
        "start",
        AsyncMock(return_value={"name": "old", "token": "old", "url": "https://example.test"}),
    )
    client.post(f"/api/notebooks/{id}/editor", json={})
    monkeypatch.setattr(
        main.editor, "read", AsyncMock(side_effect=main.HTTPException(410, "Expired"))
    )
    start = AsyncMock(return_value={"name": "new", "token": "new", "url": "https://example.test"})
    monkeypatch.setattr(main.editor, "start", start)
    response = client.post(f"/api/notebooks/{id}/editor", json={})
    assert response.status_code == 200 and response.json()["token"] == "new"
    assert "A notebook" in start.call_args.args[0]


def test_simultaneous_editor_start_is_serialized(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import anyio

    id = create(client)
    entered, release = Event(), Event()

    async def start(source, *, notebook_id):
        entered.set()
        await anyio.to_thread.run_sync(lambda: release.wait(5))
        return {"name": "one", "token": "one", "url": "https://example.test"}

    monkeypatch.setattr(main.editor, "start", start)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(client.post, f"/api/notebooks/{id}/editor", json={})
        assert entered.wait(5)
        try:
            assert client.post(f"/api/notebooks/{id}/editor", json={}).status_code == 409
        finally:
            release.set()
        assert first.result().status_code == 200


def test_render_without_system_jupyter_templates(monkeypatch):
    from nbconvert.exporters.templateexporter import TemplateExporter

    from render import render

    monkeypatch.setattr(TemplateExporter, "get_prefix_root_dirs", lambda self: [])
    html = render(new_notebook("Bundled templates"))
    assert "Bundled templates" in html
    assert "Hello, notebook." in html
    assert "jp-Notebook" in html


def test_launcher_paths_follow_remote_script_location(tmp_path, monkeypatch):
    import runpy
    import sqlite3
    import sys
    from pathlib import Path
    from types import ModuleType

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    launcher = workspace / ".notebook-editor.py"
    launcher.write_text((Path(main.__file__).parent / "assets/jupyter_launcher.py").read_text())
    module = ModuleType("jupyterlab.labapp")
    observed = []
    module.main = lambda: observed.extend(sys.argv) or 0
    monkeypatch.setitem(sys.modules, "pysqlite3", sqlite3)
    monkeypatch.setitem(sys.modules, "jupyterlab.labapp", module)
    monkeypatch.setattr(sys, "argv", [str(launcher), "notebook.ipynb"])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(launcher), run_name="__main__")
    assert result.value.code == 0
    assert f"--LabApp.templates_dir={workspace}/.jupyter/templates" in observed
    assert f"--LabApp.user_settings_dir={workspace}/.jupyter/lab/user-settings" in observed
    assert f"--ServerApp.root_dir={workspace}" in observed


def test_setup_stream_progress_ready_and_reuse(client, monkeypatch):
    import json

    id = create(client)
    result = {
        "generation": main.editor.generation(),
        "name": "streamed",
        "url": "https://example.test/editor",
        "token": "t",
    }

    async def start(source, report, *, notebook_id):
        report("progress", "Installing Python and JupyterLab…")
        report("log", "Installing ipykernel\n")
        return result

    monkeypatch.setattr(main.editor, "start", start)
    response = client.post(f"/api/notebooks/{id}/editor", headers={"Accept": "text/event-stream"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert any(e.get("message") == "Installing ipykernel\n" for e in events)
    assert events[-1] == {"type": "ready", "editor": result}
    monkeypatch.setattr(main.editor, "read", AsyncMock(return_value=new_notebook("Saved")))
    response = client.post(f"/api/notebooks/{id}/editor", headers={"Accept": "text/event-stream"})
    assert '"type": "ready"' in response.text


def test_setup_stream_failure_releases_lease(client, monkeypatch):
    id = create(client)
    monkeypatch.setattr(
        main.editor, "start", AsyncMock(side_effect=RuntimeError("private details"))
    )
    for _ in range(2):
        response = client.post(
            f"/api/notebooks/{id}/editor", headers={"Accept": "text/event-stream"}
        )
        assert '"type": "error"' in response.text
        assert "private details" not in response.text
        assert "Could not start Jupyter" in response.text
    client.cookies.clear()
    assert (
        client.post(
            f"/api/notebooks/{id}/editor", headers={"Accept": "text/event-stream"}
        ).status_code
        == 401
    )


def test_close_detaches_before_background_shutdown(client, monkeypatch):
    id = create(client)
    result = {
        "generation": main.editor.generation(),
        "name": "closing",
        "url": "https://example.test/editor",
        "token": "t",
    }
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=result))
    monkeypatch.setattr(main.editor, "read", AsyncMock(return_value=new_notebook("Durable draft")))
    client.post(f"/api/notebooks/{id}/editor")

    async def stop(current):
        row = await main.get_notebook(id)
        assert row["editor"] is None
        assert "Durable draft" in row["source"]
        raise RuntimeError("Shutdown unavailable")

    monkeypatch.setattr(main.editor, "stop", stop)
    assert client.post(f"/api/notebooks/{id}/close", json={"token": "t"}).json() == {"closed": True}
    main.editor.read.assert_awaited_once_with(result, extend=False)


def test_render_uses_stored_html_and_backfills_legacy_rows(client, monkeypatch):
    from unittest.mock import Mock

    from sqlalchemy import update

    id = create(client)
    renderer = Mock(wraps=main.render)
    monkeypatch.setattr(main, "render", renderer)
    initial = client.get(f"/api/notebooks/{id}/render")
    assert initial.status_code == 200
    renderer.assert_not_called()

    async def clear_html():
        async with main.engine.begin() as conn:
            await conn.execute(
                update(main.notebooks).where(main.notebooks.c.id == id).values(published_html=None)
            )

    client.portal.call(clear_html)
    first = client.get(f"/api/notebooks/{id}/render")
    second = client.get(f"/api/notebooks/{id}/render")
    assert first.text == second.text == initial.text
    assert renderer.call_count == 1


def test_publish_updates_html_atomically_and_drafts_leave_it_unchanged(client, monkeypatch):
    id = create(client)
    initial = client.get(f"/api/notebooks/{id}/render").text
    session = {"name": "render-test", "token": "t", "url": "https://example.test"}
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=session))
    monkeypatch.setattr(
        main.editor, "read", AsyncMock(return_value=new_notebook("New public content"))
    )
    client.post(f"/api/notebooks/{id}/editor")
    assert client.post(f"/api/notebooks/{id}/save", json={"token": "t"}).status_code == 200
    assert client.get(f"/api/notebooks/{id}/render").text == initial
    assert (
        client.post(f"/api/notebooks/{id}/save", json={"token": "t", "publish": True}).status_code
        == 200
    )
    published = client.get(f"/api/notebooks/{id}/render").text
    assert "New public content" in published
    revision = client.portal.call(main.get_notebook, id)["revision"]

    def fail_render(source):
        raise RuntimeError("Conversion failed")

    monkeypatch.setattr(main, "render", fail_render)
    monkeypatch.setattr(
        main.editor, "read", AsyncMock(return_value=new_notebook("Must not publish"))
    )
    with pytest.raises(RuntimeError, match="Conversion failed"):
        client.post(f"/api/notebooks/{id}/save", json={"token": "t", "publish": True})
    assert client.get(f"/api/notebooks/{id}/render").text == published
    assert "Must not publish" not in client.get(f"/api/notebooks/{id}/download").text
    assert client.portal.call(main.get_notebook, id)["revision"] == revision


@pytest.mark.asyncio
async def test_initialize_adds_html_to_existing_database(tmp_path, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    import db

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(db, "engine", engine)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE notebooks (id TEXT PRIMARY KEY, published TEXT)"))
            await conn.execute(
                text("INSERT INTO notebooks (id, published) VALUES ('old', 'preserved')")
            )
        await db.initialize()
        await db.initialize()
        async with engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT published, published_html FROM notebooks"))
            ).one()
            assert tuple(row) == ("preserved", None)
    finally:
        await engine.dispose()


def test_legacy_backfill_cannot_overwrite_a_new_publication(client, monkeypatch):
    import asyncio

    from sqlalchemy import update

    id = create(client)

    async def change(**values):
        async with main.engine.begin() as conn:
            await conn.execute(
                update(main.notebooks).where(main.notebooks.c.id == id).values(**values)
            )

    client.portal.call(lambda: change(published_html=None))

    def render_during_publish(source):
        asyncio.run(
            change(published=new_notebook("New revision"), published_html="New HTML", revision=2)
        )
        return "Old HTML"

    monkeypatch.setattr(main, "render", render_during_publish)
    assert client.get(f"/api/notebooks/{id}/render").text == "Old HTML"
    assert client.get(f"/api/notebooks/{id}/render").text == "New HTML"
    assert client.portal.call(main.get_notebook, id)["revision"] == 2


def test_discard_restores_published_draft_without_reading_jupyter(client, monkeypatch):
    id = create(client)
    original = client.get(f"/api/notebooks/{id}/download").text
    session = {"name": "discard-test", "token": "t", "url": "https://example.test"}
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=session))
    monkeypatch.setattr(
        main.editor, "read", AsyncMock(return_value=new_notebook("Discard this draft"))
    )
    monkeypatch.setattr(main.editor, "stop", AsyncMock())
    client.post(f"/api/notebooks/{id}/editor")
    client.post(f"/api/notebooks/{id}/save", json={"token": "t"})
    main.editor.read.reset_mock()
    assert client.post(f"/api/notebooks/{id}/discard", json={"token": "wrong"}).status_code == 409
    response = client.post(f"/api/notebooks/{id}/discard", json={"token": "t"})
    assert response.json() == {"closed": True, "discarded": True}
    main.editor.read.assert_not_awaited()
    row = client.portal.call(main.get_notebook, id)
    assert row["source"] == row["published"] == original
    assert row["editor"] is None and row["revision"] == 1
    client.post(f"/api/notebooks/{id}/editor")
    assert main.editor.start.call_args.args[0] == original


def test_save_and_exit_publishes_html_and_closes(client, monkeypatch):
    id = create(client)
    session = {"name": "save-exit-test", "token": "t", "url": "https://example.test"}
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=session))
    monkeypatch.setattr(
        main.editor, "read", AsyncMock(return_value=new_notebook("Saved and closed"))
    )
    monkeypatch.setattr(main.editor, "stop", AsyncMock())
    client.post(f"/api/notebooks/{id}/editor")
    assert (
        client.post(f"/api/notebooks/{id}/close", json={"token": "t", "publish": True}).status_code
        == 200
    )
    row = client.portal.call(main.get_notebook, id)
    assert row["editor"] is None and row["revision"] == 2
    assert "Saved and closed" in row["published_html"]


def test_blob_publication_and_failed_upload_preserve_previous_version(client, monkeypatch):
    upload = AsyncMock(return_value="https://store.public.blob.vercel-storage.com/first.html")
    monkeypatch.setattr(main.publication, "upload", upload)
    id = create(client)
    assert next(row for row in client.get("/api/notebooks").json() if row["id"] == id)[
        "render_url"
    ].endswith("/first.html")
    session = {"name": "blob-test", "token": "t", "url": "https://example.test"}
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=session))
    monkeypatch.setattr(main.editor, "read", AsyncMock(return_value=new_notebook("Private draft")))
    client.post(f"/api/notebooks/{id}/editor")
    client.post(f"/api/notebooks/{id}/save", json={"token": "t"})
    assert upload.await_count == 1
    upload.side_effect = RuntimeError("Blob upload failed")
    with pytest.raises(RuntimeError, match="Blob upload failed"):
        client.post(f"/api/notebooks/{id}/save", json={"token": "t", "publish": True})
    row = client.portal.call(main.get_notebook, id)
    assert row["render_url"].endswith("/first.html") and row["revision"] == 1
    assert "Private draft" not in row["published"]


def test_legacy_html_is_uploaded_and_reused(client, monkeypatch):
    id = create(client)
    upload = AsyncMock(return_value="https://store.public.blob.vercel-storage.com/legacy.html")
    monkeypatch.setattr(main.publication, "enabled", lambda: True)
    monkeypatch.setattr(main.publication, "upload", upload)
    assert client.get(f"/api/notebooks/{id}/render").status_code == 200
    assert client.get(f"/api/notebooks/{id}/render").status_code == 200
    upload.assert_awaited_once()
    assert client.portal.call(main.get_notebook, id)["render_url"].endswith("/legacy.html")


@pytest.mark.asyncio
async def test_blob_upload_has_isolation_policy_and_immutable_url(monkeypatch):
    from types import SimpleNamespace

    import publication

    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-token")
    put = AsyncMock(
        return_value=SimpleNamespace(url="https://store.public.blob.vercel-storage.com/test.html")
    )
    monkeypatch.setattr(publication, "put_async", put)
    await publication.upload("id", "<html><head></head><body>Published</body></html>")
    payload = put.call_args.args[1].decode()
    assert 'http-equiv="Content-Security-Policy"' in payload
    assert "connect-src &#x27;none&#x27;" in payload
    assert payload.index("Content-Security-Policy") < payload.index("<body>")
    assert put.call_args.kwargs["add_random_suffix"] is True
    assert put.call_args.kwargs["access"] == "public"


# @lat: [[chat#Chat authorization tests]]
def test_chat_requires_active_editor(client):
    id = create(client)
    response = client.post(
        f"/api/notebooks/{id}/chat",
        json={
            "token": "stale",
            "messages": [
                {"id": "u1", "role": "user", "parts": [{"type": "text", "text": "hello"}]}
            ],
        },
    )
    assert response.status_code == 409
    response = client.post(f"/api/notebooks/{id}/chat", content="x" * 1_000_001)
    assert response.status_code == 413


# @lat: [[editing#Deployment generations]]
def test_deployment_replaces_editor_without_losing_saved_draft(client, monkeypatch):
    id = create(client)
    monkeypatch.setattr(main.editor, "generation", lambda: "deployment-a")
    start = AsyncMock(return_value={"name": "old", "token": "old", "url": "https://example.test"})
    read = AsyncMock(return_value=new_notebook("Recovered draft"))
    stop = AsyncMock()
    monkeypatch.setattr(main.editor, "start", start)
    monkeypatch.setattr(main.editor, "read", read)
    monkeypatch.setattr(main.editor, "stop", stop)
    first = client.post(f"/api/notebooks/{id}/editor", json={}).json()
    assert first["generation"] == "deployment-a"
    assert client.post(f"/api/notebooks/{id}/editor", json={}).json() == first
    assert start.await_count == 1
    monkeypatch.setattr(main.editor, "generation", lambda: "deployment-b")
    start.side_effect = RuntimeError("Unavailable")
    assert client.post(f"/api/notebooks/{id}/editor", json={}).status_code == 502
    stop.assert_awaited_once_with(first)
    stop.reset_mock()
    row = client.portal.call(main.get_notebook, id)
    assert "Recovered draft" in row["source"]
    assert "Recovered draft" not in row["published"]
    start.side_effect = None
    start.return_value = {"name": "new", "token": "new", "url": "https://new.test"}
    result = client.post(f"/api/notebooks/{id}/editor", json={}).json()
    assert result["generation"] == "deployment-b"
    assert "Recovered draft" in start.call_args.args[0]
    stop.assert_awaited_once_with(first)
    assert client.post(f"/api/notebooks/{id}/save", json={"token": "old"}).status_code == 409


# @lat: [[chat#Chat Markdown and model label]]
def test_current_chat_model_tracks_configuration(client, monkeypatch):
    monkeypatch.delenv("AI_MODEL", raising=False)
    assert client.get("/api/auth/me").json()["chat_model"] == "gateway:openai/gpt-6-luna"
    monkeypatch.setenv("AI_MODEL", "gateway:anthropic/claude-sonnet-4.6")
    assert client.get("/api/auth/me").json()["chat_model"] == "gateway:anthropic/claude-sonnet-4.6"


# @lat: [[chat#Persistent history tests]]
def test_chat_history_survives_discard_and_blocks_stale_writes(client, monkeypatch):
    id = create(client)
    current = {
        "name": "sandbox",
        "url": "https://sandbox.test/token/doc/tree/notebook.ipynb",
        "token": "one",
    }
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=current))
    monkeypatch.setattr(main.editor, "stop", AsyncMock())
    client.post(f"/api/notebooks/{id}/editor")
    path = f"/api/notebooks/{id}/chat-history"
    assert client.post(path, json={"token": "one"}).json() == {"messages": [], "revision": 0}
    messages = [
        {"id": "u1", "role": "user", "parts": [{"type": "text", "text": "Plot a chart"}]},
        {
            "id": "a1",
            "role": "assistant",
            "parts": [
                {
                    "type": "tool-insert_cell",
                    "toolCallId": "c1",
                    "state": "input-available",
                    "input": {"source": "print(42)"},
                }
            ],
        },
    ]
    assert client.put(path, json={"token": "one", "revision": 0, "messages": messages}).json() == {
        "revision": 1
    }
    assert client.put(path, json={"token": "one", "revision": 0, "messages": []}).status_code == 409
    restored = client.post(path, json={"token": "one"}).json()
    assert restored["messages"][1]["parts"][0]["state"] == "output-error"
    assert "Interrupted" in restored["messages"][1]["parts"][0]["errorText"]
    # Historical tools can be sent back as context without executing them.
    main.chat.ai.ui.ai_sdk.to_messages(
        [main.chat.ai.ui.ai_sdk.UIMessage.model_validate(m) for m in restored["messages"]]
    )
    assert "chat_history" not in client.get("/api/notebooks").json()[0]
    assert client.post(f"/api/notebooks/{id}/discard", json={"token": "one"}).status_code == 200
    current["token"] = "two"
    client.post(f"/api/notebooks/{id}/editor")
    assert client.post(path, json={"token": "two"}).json() == restored
    assert client.put(path, json={"token": "one", "revision": 1, "messages": []}).status_code == 409
    assert client.put(path, json={"token": "two", "revision": 1, "messages": []}).status_code == 200
    assert client.post(path, json={"token": "two"}).json()["messages"] == []
    assert client.put(path, content="x" * 1_000_001).status_code == 413
    client.headers["origin"] = "https://evil.test"
    assert client.post(path, json={"token": "two"}).status_code == 403
    authenticate(client, "someone-else")
    assert client.post(path, json={"token": "two"}).status_code == 403
    client.cookies.clear()
    assert client.post(path, json={"token": "two"}).status_code == 401


# @lat: [[editing#Expired Sandbox persistence tests]]
def test_browser_document_survives_dead_sandbox(client, monkeypatch):
    id = create(client)
    current = {"generation": main.editor.generation(), "name": "dead", "token": "secret",
               "url": "https://example.test/secret/doc/tree/notebook.ipynb"}
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=current))
    read = AsyncMock(side_effect=RuntimeError("Sandbox is gone"))
    monkeypatch.setattr(main.editor, "read", read)
    monkeypatch.setattr(main.editor, "keep_alive", AsyncMock(side_effect=RuntimeError("Gone")))
    monkeypatch.setattr(main.editor, "stop", AsyncMock(side_effect=RuntimeError("Gone")))
    assert client.post(f"/api/notebooks/{id}/editor", json={}).status_code == 200
    source = new_notebook("Recovered browser edits")
    body = {"token": "secret", "source": source}
    assert client.post(f"/api/notebooks/{id}/save", json={**body, "token": "stale"}).status_code == 409
    assert client.post(f"/api/notebooks/{id}/save", json={**body, "source": "invalid"}).status_code == 422
    assert client.post(f"/api/notebooks/{id}/save", json=body).status_code == 200
    assert "Recovered browser edits" not in client.get(f"/api/notebooks/{id}/download").text
    assert client.post(f"/api/notebooks/{id}/close", json={**body, "publish": True}).status_code == 200
    assert "Recovered browser edits" in client.get(f"/api/notebooks/{id}/download").text
    read.assert_not_awaited()
    assert client.post(f"/api/notebooks/{id}/save", json=body).status_code == 409


# @lat: [[architecture#Notebook deletion tests]]
def test_delete_removes_notebook_and_stops_editor(client, monkeypatch):
    id = create(client)
    current = {"generation": main.editor.generation(), "name": "sandbox-delete",
               "token": "secret", "url": "https://example.test"}
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=current))
    stop = AsyncMock()
    remove = AsyncMock()
    monkeypatch.setattr(main.editor, "stop", stop)
    monkeypatch.setattr(main.publication, "remove", remove)
    delete_workspace = AsyncMock()
    monkeypatch.setattr(main.editor, "delete_workspace", delete_workspace)
    assert client.post(f"/api/notebooks/{id}/editor", json={}).status_code == 200
    assert client.post(f"/api/notebooks/{id}/delete", json={}).status_code == 200
    stop.assert_awaited_once_with(current)
    remove.assert_awaited_once_with(id)
    delete_workspace.assert_awaited_once_with(id)
    assert all(item["id"] != id for item in client.get("/api/notebooks").json())
    for suffix in ("render", "download"):
        assert client.get(f"/api/notebooks/{id}/{suffix}").status_code == 404
    assert client.post(f"/api/notebooks/{id}/delete", json={}).status_code == 404


# @lat: [[chat#Notebook rename tests]]
def test_rename_notebook_requires_current_editor_and_valid_title(client, monkeypatch):
    id = create(client)
    original = client.get(f"/api/notebooks/{id}/download").text
    current = {"name": "rename", "token": "secret", "url": "https://example.test"}
    monkeypatch.setattr(main.editor, "start", AsyncMock(return_value=current))
    assert client.post(f"/api/notebooks/{id}/editor", json={}).status_code == 200
    route = f"/api/notebooks/{id}/rename"
    assert client.post(route, json={"token": "stale", "title": "No"}).status_code == 409
    for title in (" ", "x" * 121):
        assert client.post(route, json={"token": "secret", "title": title}).status_code == 422
    response = client.post(route, json={"token": "secret", "title": "  Better title  "})
    assert response.json() == {"id": id, "title": "Better title"}
    item = next(row for row in client.get("/api/notebooks").json() if row["id"] == id)
    assert item["title"] == "Better title"
    assert item["revision"] == 1
    assert client.get(f"/api/notebooks/{id}/download").text == original
