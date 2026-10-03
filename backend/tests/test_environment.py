from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import editor
import sandbox_environment as environment


# @lat: [[editing#Prepared environment tests]]
@pytest.mark.parametrize("owner_id", [1, 2])
async def test_editor_restores_dependencies_and_injects_current_document(monkeypatch, owner_id):
    batch = SimpleNamespace(write_text=MagicMock())
    batch_context = AsyncMock()
    batch_context.__aenter__.return_value = batch
    instance = SimpleNamespace(
        fs=SimpleNamespace(batch=MagicMock(return_value=batch_context)),
        run_process=AsyncMock(return_value=SimpleNamespace(returncode=0)),
        create_process=AsyncMock(),
        stop=AsyncMock(),
        destroy=AsyncMock(),
        routes=[SimpleNamespace(port=8888, url="https://sandbox.test")],
    )
    drive = SimpleNamespace(name="workspace-drive")
    monkeypatch.setattr(editor.sandbox, "get_or_create_drive", AsyncMock(return_value=drive))
    create = AsyncMock(return_value=instance)
    monkeypatch.setattr(editor.sandbox, "create_sandbox", create)
    monkeypatch.setattr(
        editor, "prepared", lambda: {"drive_name": "deps-drive", "fingerprint": "recipe", "region": "iad1"}
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
    result = await editor._start_runtime({"id": owner_id, "sandbox_name": "nf-user-test"})
    assert create.call_args.kwargs["name"] == "nf-user-test"
    assert editor.sandbox.get_or_create_drive.call_args.kwargs["name"] == editor.workspace_drive_name("user:nf-user-test")
    assert "source" not in create.call_args.kwargs
    assert create.call_args.kwargs["mounts"]["/vercel"] is drive
    assert create.call_args.kwargs["mounts"]["/notebook-base"].mode == "snapshot"
    assert create.call_args.kwargs["persistent"] is False
    assert any(
        c.args[0] == ".vercel-notebook-jupyter-bridge.js" for c in batch.write_text.call_args_list
    )
    assert instance.run_process.await_args_list[0].args == (
        "python3", [".initialize-workspace.py", "recipe"],
    )
    assert instance.run_process.await_args_list[1].args == (
        ".venv/bin/python",
        [".patch-jupyter-template.py"],
    )
    batch.write_text.assert_any_call(".jupyter/lab/user-settings/@jupyterlab/docmanager-extension/plugin.jupyterlab-settings", '{"autosave": false, "autosaveInterval": 5}')
    batch.write_text.assert_any_call(".jupyter/lab/user-settings/@jupyterlab/apputils-extension/themes.jupyterlab-settings", '{"adaptive-theme": false, "theme": "JupyterLab Dark"}')
    assert any(c.args[0] == ".notebook-matplotlibrc" for c in batch.write_text.call_args_list)
    assert instance.run_process.await_count == 2  # No dependency or font installation.
    assert result["base_url"].startswith("https://sandbox.test/")


def test_dependency_changes_invalidate_prepared_manifest(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(environment, "ASSETS", tmp_path)
    monkeypatch.setattr(environment, "MANIFEST", tmp_path / "environment.json")
    for name in [
        "sandbox-requirements.in",
        "sandbox-requirements.lock",
        "fonts.json",
        "install_fonts.py",
        "initialize_workspace.py",
    ]:
        (tmp_path / name).write_text("original")
    with pytest.raises(RuntimeError, match="Prepare"):
        environment.prepared()
    environment.MANIFEST.write_text(
        json.dumps(
            {"fingerprint": environment.fingerprint(), "drive_name": "deps-test", "region": "iad1"}
        )
    )
    assert environment.prepared()["drive_name"] == "deps-test"
    (tmp_path / "sandbox-requirements.lock").write_text("changed")
    with pytest.raises(RuntimeError, match="dependencies changed"):
        environment.prepared()


async def test_stop_flushes_drive_before_destroying_sandbox(monkeypatch):
    events = []

    async def stop():
        events.append("stop")

    async def destroy():
        assert events == ["stop"]
        events.append("destroy")

    instance = SimpleNamespace(stop=stop, destroy=destroy)
    monkeypatch.setattr(editor.sandbox, "get_sandbox", AsyncMock(return_value=instance))

    @asynccontextmanager
    async def session():
        yield

    monkeypatch.setattr(editor, "session", session)
    await editor.stop({"name": "test"})
    assert events == ["stop", "destroy"]


def test_workspace_names_are_stable_and_isolated():
    assert editor.workspace_drive_name("one") == editor.workspace_drive_name("one")
    assert editor.workspace_drive_name("one") != editor.workspace_drive_name("two")
