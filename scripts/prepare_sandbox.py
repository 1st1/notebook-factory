"""Build and verify the immutable dependency drive used by notebook workspaces."""

import asyncio
import json
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env.local")
sys.path.insert(0, str(ROOT / "backend"))

import sandbox_environment as environment
from vercel import sandbox
from vercel.api import session


async def prepare():
    async with session():
        fingerprint = environment.fingerprint()
        existing = json.loads(environment.MANIFEST.read_text()) if environment.MANIFEST.exists() else {}
        if existing.get("fingerprint") == fingerprint and existing.get("drive_name"):
            async for drive in sandbox.query_drives():
                if drive.name == existing["drive_name"]:
                    print("Sandbox dependencies unchanged; reusing prepared drive.")
                    return
            print("Prepared drive is absent in this project; building a project-local environment.", flush=True)
        # Unique names keep concurrent builders and previous deployments isolated.
        drive = await sandbox.get_or_create_drive(
            name="nf-deps-" + fingerprint[:12] + "-" + secrets.token_hex(4),
            region=environment.REGION, max_size_bytes=2 * 1024**3,
        )
        instance = None
        verified = False
        try:
            print("Preparing dependency drive…", flush=True)
            instance = await sandbox.create_sandbox(
                name="nf-build-" + secrets.token_hex(8), region=environment.REGION,
                mounts={"/notebook-base": drive}, execution_time_limit=600, persistent=False,
            )
            await environment.install(instance, sys.stdout)
            code = f"""import shutil
from pathlib import Path
for name in ('.venv', '.local/share/uv', '.local/share/fonts/notebook-factory', '.config/matplotlib', '.cache/matplotlib'):
    source, target = Path('/vercel') / name, Path('/notebook-base') / name
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, symlinks=True)
Path('/notebook-base/.notebook-environment').write_text({fingerprint!r})
"""
            await instance.run_process(".venv/bin/python", ["-c", code], check=True, capture_output=True)
            # A graceful stop flushes and detaches the drive. Destroy alone is not sufficient.
            await instance.stop()
            await instance.destroy()
            instance = await sandbox.create_sandbox(
                name="nf-verify-" + secrets.token_hex(8), region=environment.REGION,
                mounts={"/notebook-base": drive.snapshot()}, execution_time_limit=180,
                persistent=False,
            )
            await instance.fs.write_text(".initialize-workspace.py", (environment.ASSETS / "initialize_workspace.py").read_text())
            await instance.run_process("python3", [".initialize-workspace.py", fingerprint], check=True, capture_output=True)
            await instance.run_process(".venv/bin/python", ["-c",
                "import jupyterlab, pip, numpy, pandas, scipy, seaborn, matplotlib.pyplot as plt; plt.figure().canvas.draw()"
            ], check=True, capture_output=True)
            environment.MANIFEST.write_text(json.dumps({
                "fingerprint": fingerprint, "drive_name": drive.name, "region": environment.REGION,
            }, indent=2) + "\n")
            verified = True
            print("Dependency drive verified; commit backend/assets/sandbox-environment.json.", flush=True)
        finally:
            if instance:
                await instance.stop()
                await instance.destroy()
            if not verified:
                for attempt in range(20):
                    try:
                        await drive.delete()
                        break
                    except sandbox.SandboxApiError as error:
                        if error.status_code != 409 or attempt == 19:
                            raise
                        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(prepare())
