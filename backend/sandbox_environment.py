"""Versioned, dependency-only Sandbox drives prepared before deployment."""

import hashlib
import json
from pathlib import Path

ASSETS = Path(__file__).with_name("assets")
MANIFEST = ASSETS / "sandbox-environment.json"
REGION = "iad1"


def fingerprint():
    digest = hashlib.sha256()
    for path in [
        Path(__file__),
        ASSETS / "sandbox-requirements.in",
        ASSETS / "sandbox-requirements.lock",
        ASSETS / "fonts.json",
        ASSETS / "install_fonts.py",
        ASSETS / "initialize_workspace.py",
    ]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prepared():
    if not MANIFEST.exists():
        raise RuntimeError(
            "Prepare the Sandbox environment with scripts/deploy.sh before deploying."
        )
    value = json.loads(MANIFEST.read_text())
    if value.get("fingerprint") != fingerprint() or not value.get("drive_name"):
        raise RuntimeError("Sandbox dependencies changed. Run scripts/deploy.sh to prepare them.")
    return value


async def install(instance, output):
    """Runs only in a clean builder, never in an interactive notebook session."""
    for source, target in [
        ("sandbox-requirements.lock", ".sandbox-requirements.lock"),
        ("fonts.json", ".notebook-fonts.json"),
        ("install_fonts.py", ".install-notebook-fonts.py"),
    ]:
        await instance.fs.write_text(target, (ASSETS / source).read_text())
    result = await instance.run_process(
        "sh",
        [
            "-c",
            '(command -v uv || python3 -m pip install "uv>=0.8,<1") && '
            "uv venv --seed --python 3.13 .venv && "
            "uv pip install --python .venv/bin/python -r .sandbox-requirements.lock && "
            ".venv/bin/python .install-notebook-fonts.py .notebook-fonts.json && "
            '.venv/bin/python -c "import matplotlib.pyplot as plt; plt.figure().canvas.draw()"',
        ],
        stdout=output,
        stderr=output,
        kill_after=300,
    )
    if result.returncode:
        raise RuntimeError("Sandbox environment preparation failed")
