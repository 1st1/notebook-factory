"""Seed an isolated writable workspace from the versioned dependency drive."""

import shutil
import sys
from pathlib import Path

base = Path("/notebook-base")
workspace = Path("/vercel")
fingerprint = sys.argv[1]
marker = workspace / ".notebook-environment"
if (base / ".notebook-environment").read_text().strip() != fingerprint:
    raise RuntimeError("Prepared dependency drive is incomplete or out of date")
if not marker.exists() or marker.read_text().strip() != fingerprint:
    marker.unlink(missing_ok=True)
    # Only replace managed dependencies; user files elsewhere in the workspace survive.
    for relative in (
        ".venv", ".local/share/uv", ".local/share/fonts/notebook-factory",
        ".config/matplotlib", ".cache/matplotlib",
    ):
        source, target = base / relative, workspace / relative
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, symlinks=True)
    marker.write_text(fingerprint + "\n")
