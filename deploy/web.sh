#!/usr/bin/env bash
# Interfejs WWW AktoMat na serwerze UZP: http://<adres-ip>:8000 (port otwarty wg VM.md).
#   bash repo/deploy/web.sh            # uruchom w tle (tmux albo nohup) i dodaj autostart po restarcie (cron @reboot)
#   bash repo/deploy/web.sh --stop     # zatrzymaj i usuń autostart
# Nie dotyka /opt/solution/input ani output (sesje GUI trafiają do repo/sesje). Klucz LLM z /opt/solution/.env.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SOL="${SOL:-/opt/solution}"
PORT="${PORT:-8000}"
CMD="cd $SOL && ODW2JSON_ENV=$SOL/.env PYTHONPATH=$REPO $REPO/.venv/bin/python -m odw2json web --host 0.0.0.0 --port $PORT >> $SOL/web.log 2>&1"
TAG="# aktomat-web"

stop() {
  tmux kill-session -t aktomat-web 2>/dev/null || true
  pkill -f "odw2json web --host 0.0.0.0 --port $PORT" 2>/dev/null || true
  (crontab -l 2>/dev/null | grep -v "$TAG") | crontab - || true
}

if [ "${1:-}" = "--stop" ]; then stop; echo "Zatrzymano."; exit 0; fi

stop
if command -v tmux >/dev/null; then
  tmux new -d -s aktomat-web "$CMD"
else
  nohup bash -c "$CMD" >/dev/null 2>&1 &
fi
(crontab -l 2>/dev/null | grep -v "$TAG"; echo "@reboot $CMD $TAG") | crontab -
sleep 4
if curl -fsS "http://127.0.0.1:$PORT/api/status" >/dev/null; then
  echo "GUI działa: http://$(curl -fsS -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):$PORT  (log: $SOL/web.log)"
else
  echo "[BŁĄD] GUI nie odpowiada, zobacz $SOL/web.log"; exit 1
fi
