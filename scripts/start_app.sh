#!/bin/sh
# Run locally with all application caches and temporary files inside this project.
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
mkdir -p .cache/tmp .cache/streamlit-home .cache/xdg-cache
export HOME="$PROJECT_ROOT/.cache/streamlit-home"
export TMPDIR="$PROJECT_ROOT/.cache/tmp"
export XDG_CACHE_HOME="$PROJECT_ROOT/.cache/xdg-cache"
exec .venv/bin/python -m streamlit run app.py --server.address=127.0.0.1 "$@"
