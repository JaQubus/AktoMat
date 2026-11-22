#!/usr/bin/env bash
# Przetwarza wszystkie PDF-y z /opt/solution/input do /opt/solution/output (bez interakcji, kończy się sam).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SOL="${SOL:-/opt/solution}"
cd "$SOL"
export ODW2JSON_ENV="$SOL/.env"
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"
exec "$REPO/.venv/bin/python" -m odw2json run -i "$SOL/input" -o "$SOL/output" -t "$SOL/trace"
