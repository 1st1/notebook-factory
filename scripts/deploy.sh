#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
uv run scripts/prepare_fonts.py
uv run --project backend python scripts/prepare_sandbox.py
exec npx --yes vercel@62.1.0 deploy "$@"
