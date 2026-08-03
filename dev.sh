#!/usr/bin/env bash
# One-command local run desk: inspector backend + run controller + Vite frontend,
# all in this terminal with interleaved logs. Ctrl-C stops all three.
#
#   ./dev.sh          (run it — do NOT `source` it; Ctrl-C would kill your shell)
#
# Override the Python used for the backends (must be the pipeline's env):
#   RUN_DESK_PIPELINE_PYTHON=/path/to/python ./dev.sh
set -uo pipefail
cd "$(dirname "$0")"  # repo root (this script lives at the clone root)

PYTHON="${RUN_DESK_PIPELINE_PYTHON:-python3}"

# Kill the whole process group on exit so no uvicorn/vite/esbuild is orphaned.
trap 'exit 130' INT TERM
trap 'kill 0 2>/dev/null' EXIT

if [ ! -d ui/frontend/node_modules ]; then
  echo "ui/frontend deps missing — installing once..."
  ( cd ui/frontend && npm install )
fi

echo "inspector  → http://127.0.0.1:8000   (read-only artifacts, /api/*)"
"$PYTHON" -m uvicorn ui.backend.app.main:app --host 127.0.0.1 --port 8000 --reload &

# The controller supervises live runs; --reload would terminate an active run, so
# it is intentionally omitted here (matches ui/README.md).
echo "controller → http://127.0.0.1:8001   (launches runs, /control/*)"
"$PYTHON" -m uvicorn ui.controller.app.main:create_app --factory --host 127.0.0.1 --port 8001 &

echo "frontend   → http://127.0.0.1:5173   (open this one)"
( cd ui/frontend && npm run dev ) &

echo ""
echo "Run desk starting → open http://127.0.0.1:5173   (Ctrl-C stops all three)"
wait
