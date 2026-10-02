"""Install pinned, OFL-licensed Noto fonts and default Matplotlib fallbacks."""

import hashlib
from pathlib import Path
from urllib.request import urlopen

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

COMMIT = "9710da1eacb3be272583c3224dcb70f9da6eadbb"
FONTS = [
    ("notoemoji", "NotoEmoji", "de6c18832938afc99caf132b39d6a30a19bac7f2e812e28db2535b4608d27551"),
    (
        "notosansjp",
        "NotoSansJP",
        "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f",
    ),
]


def install():
    folder = Path.home() / ".local/share/fonts/notebook-factory"
    folder.mkdir(parents=True, exist_ok=True)
    for family, filename, expected in FONTS:
        base = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/{family}"
        path = folder / f"{filename}.ttf"
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            with urlopen(f"{base}/{filename}%5Bwght%5D.ttf", timeout=40) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError(f"Font checksum mismatch: {filename}")
            path.write_bytes(data)
        with urlopen(f"{base}/OFL.txt", timeout=20) as response:
            (folder / f"{filename}-OFL.txt").write_bytes(response.read())
        # Matplotlib/FreeType may expose only a variable font's default weight.
        # Install static regular and bold faces so weight matching is unambiguous.
        for weight, style in [(400, "Regular"), (700, "Bold")]:
            target = folder / f"{filename}-{style}.ttf"
            with TTFont(path) as variable:
                font = instantiateVariableFont(
                    variable, {"wght": weight}, inplace=False, updateFontNames=True
                )
                font.save(target)
                font.close()
        path.unlink()
        print(f"Installed {filename} regular and bold", flush=True)
    config = Path.home() / ".config/matplotlib"
    config.mkdir(parents=True, exist_ok=True)
    (config / "matplotlibrc").write_text(
        "font.family: DejaVu Sans, Noto Emoji, Noto Sans JP\n"
        "font.sans-serif: DejaVu Sans, Noto Emoji, Noto Sans JP\n"
    )
    # Needed when repairing an existing environment that already imported Matplotlib.
    cache = Path.home() / ".cache/matplotlib"
    for path in cache.glob("fontlist-v*.json"):
        path.unlink()


if __name__ == "__main__":
    install()
