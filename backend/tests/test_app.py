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

    async def start(source):
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
    result = {"name": "streamed", "url": "https://example.test/editor", "token": "t"}

    async def start(source, report):
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
    result = {"name": "closing", "url": "https://example.test/editor", "token": "t"}
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
