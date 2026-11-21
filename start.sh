#!/usr/bin/env bash
# Odwołania2JSON - uruchomienie:  ./start.sh [run|web|eval --gt KATALOG|classes] [opcje]
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q --disable-pip-version-check -r requirements.txt
[ -f .env ] || cp .env.example .env
command -v tesseract >/dev/null || echo "[UWAGA] Brak Tesseract OCR (apt install tesseract-ocr tesseract-ocr-pol) - skany nie będą odczytane"
exec python -m odw2json "$@"
