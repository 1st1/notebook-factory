"""Jupyter runs in Sandbox; its WebSockets connect directly from the iframe."""

import json
import secrets
from pathlib import Path

import anyio
import httpx
from fastapi import HTTPException
from vercel import sandbox
from vercel.api import session

from config import APP_URL, MAX_BYTES

ASSETS = Path(__file__).with_name("assets")
PORT = 8888


async def start(source: str):
    token = secrets.token_urlsafe(32)
    name = "nf-" + secrets.token_hex(12)
    async with session():
        instance = await sandbox.create_sandbox(name=name, ports=[PORT], execution_time_limit=900)
        try:
            await instance.fs.write_text("notebook.ipynb", source)
            install = await instance.run_process(
                "sh",
                [
                    "-c",
                    '(command -v uv || python3 -m pip install "uv>=0.8,<1") && '
                    'uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python "jupyterlab==4.4.10" "pysqlite3-binary==0.5.4.post2"',
                ],
                capture_output=True,
                kill_after=220,
            )
            if install.returncode:
                raise RuntimeError("Jupyter dependency installation failed")
            for filename, target in {
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
                await instance.fs.write_text(target, content)
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
                await instance.fs.mkdir(folder)
                await instance.fs.write_text(
                    f"{folder}/{filename}.jupyterlab-settings", json.dumps(value)
                )
            patch = await instance.run_process(
                ".venv/bin/python", [".patch-jupyter-template.py"], capture_output=True
            )
            if patch.returncode:
                raise RuntimeError("Jupyter template patch failed")
            # A random 256-bit base path is the capability protecting all HTTP and WS routes.
            # This avoids third-party cookie dependencies in embedded Jupyter.
            await instance.create_process(
                ".venv/bin/python",
                [
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
                    "--LabApp.user_settings_dir=/vercel/sandbox/.jupyter/lab/user-settings",
                    "--LabApp.templates_dir=/vercel/sandbox/.jupyter/templates",
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
            raise RuntimeError("Jupyter startup timed out")
        except BaseException:
            with anyio.CancelScope(shield=True):
                await instance.stop()
            raise


async def read(editor: dict):
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
        await current.extend_execution_time_limit(30)
        return body.decode()


async def stop(editor: dict):
    async with session():
        instance = await sandbox.get_sandbox(name=editor["name"])
        await instance.stop()
