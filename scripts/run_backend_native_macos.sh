#!/usr/bin/env bash
set -euo pipefail

# Start the Jarvis FastAPI backend on the REAL macOS host (host Python, host TCC permissions).
# Do not run this inside a Linux container — Finder, AppleScript, open, and Path.home() must be macOS.

if [[ -f /.dockerenv ]]; then
  echo "ERROR: Refusing to start — /.dockerenv present. Run this script from macOS Terminal on your Mac,"
  echo "       not inside Docker. Use docker-compose only for optional services (e.g. Ollama)."
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

PY=""
if [[ -x .venv/bin/python ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "ERROR: No Python found. Create a venv: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Jarvis API — host-native macOS"
echo "  Python: $PY"
echo "  Cwd:    $ROOT/backend"
echo "  Docs:   README → macOS manual permission checklist"
echo ""

exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 "$@"
