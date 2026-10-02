import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "install_fonts", Path(__file__).parents[1] / "assets/install_fonts.py"
)
fonts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fonts)


def bundle(extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in fonts.FILES:
            archive.writestr(name, b"font-or-license")
        if extra:
            archive.writestr(extra, b"unexpected")
    return output.getvalue()


# @lat: [[editing#Font bundle verification]]
def test_font_bundle_installs_verified_files_and_clears_old_faces(tmp_path, monkeypatch):
    data = bundle()
    monkeypatch.setattr(fonts.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(fonts, "urlopen", lambda *a, **k: io.BytesIO(data))
    folder = tmp_path / ".local/share/fonts/notebook-factory"
    folder.mkdir(parents=True)
    (folder / "NotoEmoji.ttf").write_bytes(b"old-variable-font")
    fonts.install(
        {"url": "https://blob.test/fonts.zip", "sha256": hashlib.sha256(data).hexdigest()}
    )
    assert {p.name for p in folder.iterdir()} == fonts.FILES
    assert "Noto Sans JP" in (tmp_path / ".config/matplotlib/matplotlibrc").read_text()


@pytest.mark.parametrize("invalid", ["checksum", "../escape.ttf"])
def test_font_bundle_rejects_corruption_and_unexpected_files(tmp_path, monkeypatch, invalid):
    data = bundle(None if invalid == "checksum" else invalid)
    monkeypatch.setattr(fonts.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(fonts, "urlopen", lambda *a, **k: io.BytesIO(data))
    with pytest.raises(RuntimeError):
        fonts.install(
            {
                "url": "https://blob.test/fonts.zip",
                "sha256": "bad" if invalid == "checksum" else hashlib.sha256(data).hexdigest(),
            }
        )
    assert not list(tmp_path.rglob("*.ttf"))
