# /// script
# requires-python = ">=3.12"
# dependencies = ["fonttools==4.60.1", "vercel>=0.5,<0.6", "python-dotenv>=1,<2"]
# ///
"""Build immutable font assets once; publish a pinned Blob manifest for deployments."""

import argparse
import asyncio
import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

from dotenv import load_dotenv
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from vercel.blob import put_async

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "backend/assets/fonts.json"
COMMIT = "9710da1eacb3be272583c3224dcb70f9da6eadbb"
FONTS = [
    (
        "notoemoji",
        "NotoEmoji",
        "de6c18832938afc99caf132b39d6a30a19bac7f2e812e28db2535b4608d27551",
    ),
    (
        "notosansjp",
        "NotoSansJP",
        "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f",
    ),
]


def recipe():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def build():
    archive = io.BytesIO()
    with (
        tempfile.TemporaryDirectory() as directory,
        zipfile.ZipFile(
            archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as bundle,
    ):
        for family, filename, expected in FONTS:
            base = (
                f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/{family}"
            )
            with urlopen(f"{base}/{filename}%5Bwght%5D.ttf", timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError(f"Font checksum mismatch: {filename}")
            for weight, style in [(400, "Regular"), (700, "Bold")]:
                with TTFont(io.BytesIO(data), recalcTimestamp=False) as variable:
                    font = instantiateVariableFont(
                        variable, {"wght": weight}, inplace=False, updateFontNames=True
                    )
                    target = Path(directory) / f"{filename}-{style}.ttf"
                    font.save(target)
                    font.close()
                entry = zipfile.ZipInfo(target.name)
                entry.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(entry, target.read_bytes())
            with urlopen(f"{base}/OFL.txt", timeout=30) as response:
                bundle.writestr(zipfile.ZipInfo(f"{filename}-OFL.txt"), response.read())
            print(f"Prepared {filename} regular and bold", flush=True)
    return archive.getvalue()


async def prepare(env_file=None):
    if MANIFEST.exists() and json.loads(MANIFEST.read_text()).get("recipe") == recipe():
        print("Font bundle unchanged; reusing published Blob.")
        return
    if env_file:
        load_dotenv(env_file)
    if not os.getenv("BLOB_READ_WRITE_TOKEN"):
        raise RuntimeError(
            "Set BLOB_READ_WRITE_TOKEN or pass --env-file when preparing new fonts."
        )
    data = build()
    digest = hashlib.sha256(data).hexdigest()
    result = await put_async(
        f"assets/fonts/{digest}.zip",
        data,
        access="public",
        content_type="application/zip",
        add_random_suffix=True,
        cache_control_max_age=31536000,
    )
    MANIFEST.write_text(
        json.dumps({"recipe": recipe(), "url": result.url, "sha256": digest}, indent=2)
        + "\n"
    )
    print(
        f"Published font bundle ({len(data):,} bytes). Commit backend/assets/fonts.json."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    asyncio.run(prepare(parser.parse_args().env_file))
