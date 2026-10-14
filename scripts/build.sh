#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${MUSICFLOW_PYTHON:-.venv/bin/python}"
(cd frontend && npm run build)
"$PYTHON_BIN" scripts/generate_icon.py
"$PYTHON_BIN" setup.py py2app
echo "Готово: dist/MusicFlow.app"
