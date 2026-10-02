import sys
import pysqlite3
from pathlib import Path

sys.modules["sqlite3"] = pysqlite3
import jupyterlab

source_path = Path(jupyterlab.__file__).parent / "static" / "index.html"
source = source_path.read_text()
if "jupyter-config-data" not in source or "main." not in source:
    raise RuntimeError("The installed JupyterLab index is missing its application bundle")
css = Path(".vercel-notebook-focused-editor.css").read_text()
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
