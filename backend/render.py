from html import escape
from pathlib import Path

import nbformat
from fastapi import HTTPException

from config import MAX_BYTES

CONTENT_POLICY = "default-src 'none'; base-uri 'none'; form-action 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; style-src 'unsafe-inline' https:; img-src data: https:; font-src data: https:; connect-src 'none'; frame-src 'none'"


def themed_html(html: str):
    if 'id="notebook-factory-theme"' in html:
        return html
    root = Path(__file__).parent
    css = (root / "templates/lab/static/theme-dark.css").read_text()
    css += (root / "assets/notebook_theme.css").read_text()
    css += "main{max-width:none;margin:0;padding:24px!important}.jp-Notebook{padding:0!important}"
    return html.replace("</head>", '<style id="notebook-factory-theme">' + css + "</style></head>", 1)


def isolated_html(html: str):
    # srcdoc has no HTTP response headers; put the policy before all notebook content.
    policy = (
        '<meta http-equiv="Content-Security-Policy" content="'
        + escape(CONTENT_POLICY, quote=True)
        + '">'
    )
    return themed_html(html).replace("<head>", "<head>" + policy, 1)


def validate(source: str):
    if len(source.encode()) > MAX_BYTES:
        raise HTTPException(413, "Notebook exceeds 10 MB")
    try:
        notebook = nbformat.reads(source, as_version=4)
        nbformat.validate(notebook)
        return notebook
    except Exception:
        raise HTTPException(422, "Invalid Jupyter notebook") from None


def render(source: str):
    from nbconvert import HTMLExporter

    templates = str(Path(__file__).with_name("templates"))
    exporter = HTMLExporter(
        template_name="lab",
        theme="dark",
        extra_template_basedirs=[templates],
        extra_template_paths=[templates],
    )
    exporter.exclude_input_prompt = False
    exporter.exclude_output_prompt = False
    html, _ = exporter.from_notebook_node(validate(source))
    return themed_html(html)


def new_notebook(title: str, prompt: str = ""):
    introduction = prompt.strip() or "Start with a question. Make something worth sharing. Or ask the agent to do it for you."
    return nbformat.writes(
        nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_markdown_cell(
                    "# " + title + "\n\n" + introduction
                ),
                nbformat.v4.new_code_cell('print("Hello, notebook.")'),
            ],
            metadata={
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                }
            },
        )
    )
