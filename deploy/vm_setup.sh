#!/usr/bin/env bash
# Jednorazowa instalacja AktoMat na maszynie UZP (Ubuntu 24.04, bez GPU), wg VM.md z repo organizatora.
#   cd /opt/solution && git clone <repo> repo && bash repo/deploy/vm_setup.sh
# Potem wpisz klucz API do /opt/solution/.env (opcjonalnie; bez klucza działają same reguły).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SOL="${SOL:-/opt/solution}"

sudo apt-get update -y
sudo apt-get install -y software-properties-common tesseract-ocr tesseract-ocr-pol
# Python 3.13 (wymóg UZP) z deadsnakes; w razie niepowodzenia zostaje systemowy 3.12 (kod działa także na nim)
if ! command -v python3.13 >/dev/null; then
  (sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get update -y \
     && sudo apt-get install -y python3.13 python3.13-venv) || echo "[UWAGA] brak Python 3.13, używam $(python3 --version)"
fi
PY="$(command -v python3.13 || command -v python3)"
[ -d "$REPO/.venv" ] || "$PY" -m venv "$REPO/.venv"
"$REPO/.venv/bin/pip" install -q --disable-pip-version-check -r "$REPO/requirements.txt"

mkdir -p "$SOL/input" "$SOL/output"
[ -f "$SOL/.env" ] || cp "$REPO/.env.example" "$SOL/.env"
cp "$REPO/deploy/RUN.md" "$SOL/RUN.md"
chmod +x "$REPO/deploy/run.sh"

echo "--- kontrola ---"
tesseract --list-langs 2>/dev/null | grep -qx pol && echo "Tesseract: pol OK" || echo "[BŁĄD] Tesseract bez języka pol"
"$REPO/.venv/bin/python" --version
"$REPO/.venv/bin/python" -m pytest -q "$REPO/tests" | tail -1
echo "Gotowe. Test jak u oceniających: wrzuć PDF-y do $SOL/input, wyczyść $SOL/output i uruchom komendę z $SOL/RUN.md"
