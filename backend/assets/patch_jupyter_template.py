from importlib.util import find_spec
from pathlib import Path

# This is a top-level package: finding its spec does not execute __init__.py.
spec = find_spec("jupyterlab")
if spec is None or not spec.submodule_search_locations:
    raise RuntimeError("JupyterLab is not installed or is not a package")
package_dir = Path(next(iter(spec.submodule_search_locations)))
source_path = package_dir / "static" / "index.html"
source = source_path.read_text()
if "jupyter-config-data" not in source or "main." not in source:
    raise RuntimeError("The installed JupyterLab index is missing its application bundle")
css = Path(".vercel-notebook-focused-editor.css").read_text()
theme = Path(".notebook-theme.css")
if theme.exists():
    css += "\n" + theme.read_text()
bridge = Path(".vercel-notebook-jupyter-bridge.js").read_text()
marker = "<!-- vercel-notebook-save-bridge -->"
if 'id="vercel-notebook-focused-editor"' not in source:
    source = source.replace(
        "</head>",
        f'<style id="vercel-notebook-focused-editor">\n{css}\n</style>\n</head>',
        1,
    )
if marker not in source:
    source = source.replace("</body>", f"{marker}\n<script>\n{bridge}\n</script>\n</body>", 1)
target = Path(".jupyter/templates/index.html")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(source)
