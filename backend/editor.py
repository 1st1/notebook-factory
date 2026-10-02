"""Jupyter runs in Sandbox; its WebSockets connect directly from the iframe."""

import hashlib
import json
import os
import secrets
from pathlib import Path

import anyio
import httpx
from fastapi import HTTPException
from vercel import sandbox
from vercel.api import session

from config import APP_URL, MAX_BYTES
from sandbox_environment import prepared

ASSETS = Path(__file__).with_name("assets")
PORT = 8888


def generation():
    deployment = os.getenv("VERCEL_DEPLOYMENT_ID") or os.getenv("VERCEL_URL")
    if deployment:
        return deployment
    # Local development also invalidates environments when their bundled assets change.
    digest = hashlib.sha256()
    for path in [
        Path(__file__),
        Path(__file__).with_name("pyproject.toml"),
        *sorted(ASSETS.iterdir()),
    ]:
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return "local-" + digest.hexdigest()[:16]


def workspace_drive_name(notebook_id: str):
    return "nf-workspace-" + hashlib.sha256(notebook_id.encode()).hexdigest()[:32]


async def start(source: str, report=lambda kind, message: None, *, notebook_id: str):
    token = secrets.token_urlsafe(32)
    name = "nf-" + secrets.token_hex(12)
    async with session():
        environment = prepared()
        report("progress", "Attaching your notebook workspace…")
        drive = await sandbox.get_or_create_drive(
            name=workspace_drive_name(notebook_id), region=environment["region"],
            max_size_bytes=4 * 1024**3,
        )
        for attempt in range(30):
            try:
                instance = await sandbox.create_sandbox(
                    name=name, ports=[PORT], execution_time_limit=900, persistent=False,
                    region=environment["region"],
                    mounts={"/vercel": drive, "/notebook-base": sandbox.DriveMount(environment["drive_name"], mode="snapshot")},
                )
                break
            except sandbox.SandboxApiError as error:
                if error.status_code != 409 or attempt == 29:
                    raise
                report("progress", "Waiting for the previous editor to release its workspace…")
                await anyio.sleep(1)
        try:
            files = {"notebook.ipynb": source}
            report("progress", "Configuring the notebook editor…")
            for filename, target in {
                "initialize_workspace.py": ".initialize-workspace.py",
                "jupyter_launcher.py": ".notebook-editor.py",
                "patch_jupyter_template.py": ".patch-jupyter-template.py",
                "sitecustomize.py": "sitecustomize.py",
                "focused_editor.css": ".vercel-notebook-focused-editor.css",
                "jupyter_bridge.js": ".vercel-notebook-jupyter-bridge.js",
            }.items():
                content = (
                    (ASSETS / filename)
                    .read_text()
                    .replace("__PARENT_ORIGIN__", json.dumps(APP_URL))
                )
                files[target] = content
            settings = {
                "docmanager-extension/plugin": {
                    "autosave": True,
                    "autosaveInterval": 5,
                },
                "application-extension/shell": {"startMode": "single"},
                "application-extension/context-menu": {"disabled": True},
                "apputils-extension/themes": {
                    "adaptive-theme": False,
                    "theme": "JupyterLab Light",
                },
                "apputils-extension/notification": {
                    "checkForUpdates": False,
                    "fetchNews": "false",
                },
                "statusbar-extension/plugin": {"visible": False},
            }
            for key, value in settings.items():
                directory, filename = key.split("/")
                folder = f".jupyter/lab/user-settings/@jupyterlab/{directory}"
                files[f"{folder}/{filename}.jupyterlab-settings"] = json.dumps(value)
            async with instance.fs.batch() as batch:
                for target, content in files.items():
                    batch.write_text(target, content)
            report("progress", "Preparing workspace dependencies (cached after first use)…")
            initialized = await instance.run_process(
                "python3", [".initialize-workspace.py", environment["fingerprint"]], capture_output=True,
            )
            if initialized.returncode:
                raise RuntimeError("Workspace dependency initialization failed")
            patch = await instance.run_process(
                ".venv/bin/python", [".patch-jupyter-template.py"], capture_output=True
            )
            if patch.returncode:
                raise RuntimeError(f"Jupyter template patch failed: {patch.stderr[-3000:]}")
            report("progress", "Starting JupyterLab…")
            # A random 256-bit base path is the capability protecting all HTTP and WS routes.
            # This avoids third-party cookie dependencies in embedded Jupyter.
            await instance.create_process(
                "sh",
                [
                    "-c",
                    'exec "$@" > .jupyter.log 2>&1',
                    "notebook-factory",
                    ".venv/bin/python",
                    ".notebook-editor.py",
                    "--ip=0.0.0.0",
                    f"--port={PORT}",
                    "--no-browser",
                    "--ServerApp.allow_remote_access=True",
                    "--ServerApp.disable_check_xsrf=True",
                    "--ServerApp.allow_unauthenticated_access=True",
                    "--IdentityProvider.token=",
                    "--ServerApp.password=",
                    "--LabApp.expose_app_in_browser=True",
                    f"--ServerApp.base_url=/{token}/",
                    "--ServerApp.tornado_settings="
                    + json.dumps(
                        {
                            "headers": {
                                "Content-Security-Policy": f"frame-ancestors {APP_URL}",
                                "Referrer-Policy": "no-referrer",
                            }
                        }
                    ),
                    "notebook.ipynb",
                ],
            )
            route = next(route.url.rstrip("/") for route in instance.routes if route.port == PORT)
            url = f"{route}/{token}/doc/tree/notebook.ipynb"
            report("progress", "Waiting for JupyterLab to respond…")
            async with httpx.AsyncClient(timeout=3, follow_redirects=True) as client:
                deadline = anyio.current_time() + 45
                while anyio.current_time() < deadline:
                    try:
                        response = await client.get(url)
                        if response.status_code == 200 and "jupyter-config-data" in response.text:
                            return {"name": name, "url": url, "token": token}
                    except httpx.HTTPError:
                        pass
                    await anyio.sleep(0.5)
            output = await instance.fs.read_text(".jupyter.log")
            raise RuntimeError(
                "Jupyter startup timed out: " + output[-6000:].replace(token, "[redacted]")
            )
        except BaseException:
            with anyio.CancelScope(shield=True):
                await instance.stop()
                await instance.destroy()
            raise


async def read(editor: dict, *, extend=True):
    async with session():
        try:
            instance = await sandbox.get_sandbox(name=editor["name"])
        except sandbox.SandboxApiError as error:
            if error.status_code == 404:
                raise HTTPException(410, "Editor expired. Reopen the saved draft.") from None
            raise
        current = instance.current_session
        if current is None or current.status != sandbox.SandboxStatus.RUNNING:
            raise HTTPException(410, "Editor expired. Reopen it to restore the last saved draft.")
        # A bounded HTTP read avoids loading an unbounded notebook into the function.
        base = editor["url"].split("/doc/tree/", 1)[0]
        async with httpx.AsyncClient(timeout=20) as client:
            async with client.stream("GET", base + "/files/notebook.ipynb") as response:
                if response.status_code != 200:
                    raise HTTPException(410, "Editor unavailable. Reopen the saved draft.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise HTTPException(413, "Notebook exceeds 10 MB")
        if extend:
            await current.extend_execution_time_limit(30)
        return body.decode()


async def stop(editor: dict):
    async with session():
        try:
            instance = await sandbox.get_sandbox(name=editor["name"])
        except sandbox.SandboxApiError as error:
            if error.status_code == 404:
                return
            raise
        await instance.stop()
        await instance.destroy()


async def delete_workspace(notebook_id: str):
    async with session():
        for attempt in range(30):
            try:
                await sandbox.delete_drive(name=workspace_drive_name(notebook_id))
                return
            except sandbox.SandboxApiError as error:
                if error.status_code == 404:
                    return
                if error.status_code != 409 or attempt == 29:
                    raise
                await anyio.sleep(1)


async def keep_alive(editor: dict):
    async with session():
        instance = await sandbox.get_sandbox(name=editor["name"])
        current = instance.current_session
        if current is not None and current.status == sandbox.SandboxStatus.RUNNING:
            await current.extend_execution_time_limit(30)
