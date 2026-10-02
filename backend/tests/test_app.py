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
