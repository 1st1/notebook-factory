#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
uv run scripts/prepare_fonts.py
exec npx --yes vercel@62.1.0 deploy "$@"
