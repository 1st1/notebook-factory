"""Download prepared fonts from Blob; no font conversion in the Sandbox."""

import hashlib
import io
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen
import zipfile

FILES = {
    f"{family}-{suffix}"
    for family in ("NotoEmoji", "NotoSansJP")
    for suffix in ("Regular.ttf", "Bold.ttf", "OFL.txt")
}


def install(manifest):
    started = time.monotonic()
    print("Downloading prepared fonts from Blob…", flush=True)
    with urlopen(manifest["url"], timeout=45) as response:
        data = response.read(30_000_001)
    if len(data) > 30_000_000 or hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise RuntimeError("Font bundle checksum mismatch")
    folder = Path.home() / ".local/share/fonts/notebook-factory"
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        if (
            set(bundle.namelist()) != FILES
            or sum(f.file_size for f in bundle.infolist()) > 60_000_000
        ):
            raise RuntimeError("Unexpected font bundle contents")
        for name in FILES:
            (folder / name).write_bytes(bundle.read(name))
    # Remove legacy variable faces when upgrading an existing environment.
    for family in ("NotoEmoji", "NotoSansJP"):
        (folder / f"{family}.ttf").unlink(missing_ok=True)
    config = Path.home() / ".config/matplotlib"
    config.mkdir(parents=True, exist_ok=True)
    (config / "matplotlibrc").write_text(
        "font.family: DejaVu Sans, Noto Emoji, Noto Sans JP\n"
        "font.sans-serif: DejaVu Sans, Noto Emoji, Noto Sans JP\n"
    )
    for path in (Path.home() / ".cache/matplotlib").glob("fontlist-v*.json"):
        path.unlink()
    print(f"Installed prepared fonts in {time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    install(json.loads(Path(sys.argv[1]).read_text()))
