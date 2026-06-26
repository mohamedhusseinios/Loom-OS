#!/usr/bin/env bash
# run.sh — Start the entire Agentic OS stack (daemon + dashboard) with one command.
set -uo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --------------- cleanup ---------------
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
  echo -e "${YELLOW}Creating virtualenv...${NC}"
  python3 -m venv "$PROJECT_ROOT/.venv" || {
    echo -e "${RED}Failed to create .venv${NC}"
    exit 1
  }
fi
source "$PROJECT_ROOT/.venv/bin/activate"

# --------------- daemon deps ---------------
if ! command -v loom &>/dev/null; then
  echo -e "${YELLOW}Installing daemon (pip install -e .)...${NC}"
  cd "$PROJECT_ROOT"
  pip install -e ".[dev]" --quiet || {
    echo -e "${RED}Failed to install daemon. Check pyproject.toml dependencies.${NC}"
    exit 1
  }
  echo -e "${GREEN}Daemon installed.${NC}"
fi

# --------------- dashboard deps ---------------
if [ ! -d "$PROJECT_ROOT/dashboard/node_modules" ]; then
  echo -e "${YELLOW}Installing dashboard dependencies (npm install)...${NC}"
  cd "$PROJECT_ROOT/dashboard"
  npm install --silent || {
    echo -e "${RED}Failed to install dashboard dependencies.${NC}"
    exit 1
  }
  cd "$PROJECT_ROOT"
  echo -e "${GREEN}Dashboard deps installed.${NC}"
fi

# --------------- launch ---------------
echo ""
echo -e "${GREEN}=== Agentic OS ===${NC}"
echo "Daemon    → http://127.0.0.1:8472"
echo "Dashboard → http://localhost:3000"
echo "Press Ctrl+C to stop."
echo ""

# Start daemon
loom start --host 127.0.0.1 --port 8472 &
DAEMON_PID=$!
sleep 1
if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
  echo -e "${RED}Daemon failed to start. Check logs above for errors.${NC}"
  exit 1
fi
echo -e "${GREEN}[daemon]${NC} started (pid=$DAEMON_PID)"

# Start dashboard
cd "$PROJECT_ROOT/dashboard"
npm run dev -- -p 3000 &
DASHBOARD_PID=$!
cd "$PROJECT_ROOT"
sleep 2
if ! kill -0 "$DASHBOARD_PID" 2>/dev/null; then
  echo -e "${RED}Dashboard failed to start. Check logs above for errors.${NC}"
  exit 1
fi
echo -e "${GREEN}[dashboard]${NC} started (pid=$DASHBOARD_PID)"

# Block until either process exits (bash 3.2 compat — no wait -n)
wait "$DAEMON_PID" "$DASHBOARD_PID" 2>/dev/null || true
