from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import editor
import sandbox_environment as environment


# @lat: [[editing#Prepared environment tests]]
async def test_editor_restores_dependencies_and_injects_current_document(monkeypatch):
    batch = SimpleNamespace(write_text=MagicMock())
    batch_context = AsyncMock()
    batch_context.__aenter__.return_value = batch
    instance = SimpleNamespace(
        fs=SimpleNamespace(batch=MagicMock(return_value=batch_context)),
        run_process=AsyncMock(return_value=SimpleNamespace(returncode=0)),
        create_process=AsyncMock(),
        stop=AsyncMock(),
        routes=[SimpleNamespace(port=8888, url="https://sandbox.test")],
    )
    create = AsyncMock(return_value=instance)
    monkeypatch.setattr(editor.sandbox, "create_sandbox", create)
    monkeypatch.setattr(
        editor, "prepared", lambda: {"snapshot_id": "snap-prepared", "region": "iad1"}
    )

    @asynccontextmanager
    async def session():
        yield

    @asynccontextmanager
    async def http_client(**kwargs):
        yield SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(status_code=200, text="jupyter-config-data"))
        )

    monkeypatch.setattr(editor, "session", session)
    monkeypatch.setattr(editor.httpx, "AsyncClient", http_client)
    result = await editor.start("private notebook source")
    assert create.call_args.kwargs["source"].snapshot_id == "snap-prepared"
    assert create.call_args.kwargs["persistent"] is False
    batch.write_text.assert_any_call("notebook.ipynb", "private notebook source")
    assert any(
        c.args[0] == ".vercel-notebook-jupyter-bridge.js" for c in batch.write_text.call_args_list
    )
    assert instance.run_process.await_args_list[0].args == (
        ".venv/bin/python",
        [".patch-jupyter-template.py"],
    )
    assert instance.run_process.await_count == 1  # No dependency or font installation.
    assert result["token"] in result["url"]


def test_dependency_changes_invalidate_prepared_manifest(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(environment, "ASSETS", tmp_path)
    monkeypatch.setattr(environment, "MANIFEST", tmp_path / "environment.json")
    for name in [
        "sandbox-requirements.in",
        "sandbox-requirements.lock",
        "fonts.json",
        "install_fonts.py",
    ]:
        (tmp_path / name).write_text("original")
    with pytest.raises(RuntimeError, match="Prepare"):
        environment.prepared()
    environment.MANIFEST.write_text(
        json.dumps(
            {"fingerprint": environment.fingerprint(), "snapshot_id": "snap-test", "region": "iad1"}
        )
    )
    assert environment.prepared()["snapshot_id"] == "snap-test"
    (tmp_path / "sandbox-requirements.lock").write_text("changed")
    with pytest.raises(RuntimeError, match="dependencies changed"):
        environment.prepared()
