import runpy
import sys
from pathlib import Path


# @lat: [[editing#Template discovery tests]]
def test_patch_locates_package_without_importing_it(tmp_path, monkeypatch):
    package = tmp_path / "jupyterlab"
    (package / "static").mkdir(parents=True)
    (package / "__init__.py").write_text("raise AssertionError('JupyterLab must not be imported')")
    (package / "static/index.html").write_text(
        '<html><head></head><body><script id="jupyter-config-data"></script>'
        '<script src="main.js"></script></body></html>'
    )
    (tmp_path / ".vercel-notebook-focused-editor.css").write_text("/* focused CSS */")
    (tmp_path / ".vercel-notebook-jupyter-bridge.js").write_text("/* bridge JS */")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "jupyterlab", raising=False)
    monkeypatch.chdir(tmp_path)
    script = Path(__file__).resolve().parents[1] / "assets/patch_jupyter_template.py"
    runpy.run_path(str(script))
    output = (tmp_path / ".jupyter/templates/index.html").read_text()
    assert "focused CSS" in output and "bridge JS" in output
    assert 'src="main.js"' in output
    assert "jupyterlab" not in sys.modules
