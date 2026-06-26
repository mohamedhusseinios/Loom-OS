#!/usr/bin/env bash
# run.sh — Start the entire Agentic OS stack (daemon + dashboard) with one command.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# --------------- helpers ---------------
cleanup() {
  echo ""
  echo "Shutting down..."
  [ -n "${DAEMON_PID:-}" ] && kill "$DAEMON_PID" 2>/dev/null || true
  [ -n "${DASHBOARD_PID:-}" ] && kill "$DASHBOARD_PID" 2>/dev/null || true
  wait 2>/dev/null
  echo "All processes stopped."
}
trap cleanup EXIT INT TERM

# --------------- venv ---------------
if [ ! -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
  echo "Error: virtualenv not found at .venv/"
  echo "  Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
  exit 1
fi
source "$PROJECT_ROOT/.venv/bin/activate"

# --------------- dashboard deps ---------------
if [ ! -d "$PROJECT_ROOT/dashboard/node_modules" ]; then
  echo "Installing dashboard dependencies..."
  cd "$PROJECT_ROOT/dashboard"
  npm install
  cd "$PROJECT_ROOT"
fi

# --------------- launch ---------------
echo "=== Agentic OS ==="
echo "Daemon   → http://127.0.0.1:8472"
echo "Dashboard → http://localhost:3000"
echo "Press Ctrl+C to stop."
echo ""

# Start daemon in background
loom --host 127.0.0.1 --port 8472 &
DAEMON_PID=$!

# Start dashboard in background
cd "$PROJECT_ROOT/dashboard"
npm run dev -- -p 3000 &
DASHBOARD_PID=$!
cd "$PROJECT_ROOT"

# Wait for either to exit
wait -n "$DAEMON_PID" "$DASHBOARD_PID" 2>/dev/null || true
