#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
(cd frontend && npm run build)
exec .venv/bin/python desktop.py
