"""Prepare or validate the clean shared dependency snapshot before deploying."""

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
        if environment.MANIFEST.exists():
            value = json.loads(environment.MANIFEST.read_text())
            if value.get("fingerprint") == environment.fingerprint():
                try:
                    snapshot = await sandbox.get_snapshot(
                        snapshot_id=value["snapshot_id"]
                    )
                except sandbox.SandboxApiError as error:
                    if error.status_code != 404:
                        raise
                else:
                    if str(snapshot.status) == "created":
                        print(
                            "Sandbox dependencies unchanged; reusing prepared snapshot."
                        )
                        return
        print("Preparing clean Sandbox dependency environment…", flush=True)
        instance = await sandbox.create_sandbox(
            name="nf-build-" + secrets.token_hex(8),
            region=environment.REGION,
            execution_time_limit=600,
            persistent=False,
        )
        captured = False
        try:
            await environment.install(instance, sys.stdout)
            print("Capturing dependency snapshot…", flush=True)
            snapshot = await instance.snapshot(expiration=0)
            captured = True
            # Verify the snapshot boots with the complete environment before publishing it.
            restored = await sandbox.create_sandbox(
                name="nf-verify-" + secrets.token_hex(8),
                region=environment.REGION,
                source=sandbox.SnapshotSource(snapshot_id=snapshot.id),
                execution_time_limit=120,
                persistent=False,
            )
            try:
                result = await restored.run_process(
                    ".venv/bin/python",
                    [
                        "-c",
                        "import jupyterlab, pip, numpy, pandas, scipy, seaborn, matplotlib.pyplot as plt; plt.figure().canvas.draw(); from pathlib import Path; assert not Path('notebook.ipynb').exists()",
                    ],
                    capture_output=True,
                )
                if result.returncode:
                    raise RuntimeError(
                        "Prepared snapshot verification failed: "
                        + result.stderr[-2000:]
                    )
            finally:
                await restored.stop()
            environment.MANIFEST.write_text(
                json.dumps(
                    {
                        "fingerprint": environment.fingerprint(),
                        "snapshot_id": snapshot.id,
                        "region": environment.REGION,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(
                "Prepared snapshot verified. Commit backend/assets/sandbox-environment.json."
            )
        finally:
            if not captured:
                await instance.stop()


if __name__ == "__main__":
    asyncio.run(prepare())
