#!/usr/bin/env bash
# Render the architecture page to docs/architecture.png for Devpost and the README.
#
# The diagram lives as HTML rather than as a drawing so its numbers come from
# the same place everything else does, and so it can be re-shot after a change
# instead of being redrawn by hand and quietly drifting from the code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8095}"
PY="${PY:-$ROOT/.venv/bin/python}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
OUT="$ROOT/docs/architecture.png"

if [[ ! -x "$CHROME" ]]; then
  echo "Chrome not found at: $CHROME" >&2
  echo "Set CHROME=/path/to/chrome and re-run." >&2
  exit 1
fi

mkdir -p "$ROOT/docs"
"$PY" -m uvicorn web.app:app --host 127.0.0.1 --port "$PORT" >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
sleep 5

"$CHROME" --headless --disable-gpu --hide-scrollbars \
  --window-size=1600,1500 --virtual-time-budget=8000 \
  --screenshot="$OUT" "http://127.0.0.1:$PORT/architecture" 2>/dev/null

echo "wrote $OUT"
ls -la "$OUT"
