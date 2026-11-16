#!/usr/bin/env bash
# run.sh — Start the entire Loom OS stack (daemon + dashboard) with one command.
#
# Usage:
#   ./run.sh                          # daemon :8472, dashboard :3000
#   ./run.sh --open                   # also open the dashboard in a browser
#   ./run.sh --reload                 # daemon auto-reload (passed to loom start)
#   ./run.sh --port 9000              # daemon on :9000
#   ./run.sh --auth-token secret      # team mode
#   ./run.sh --dashboard-port 3001    # Next.js on :3001
#   ./run.sh --help
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Colors only when stdout is a TTY (keeps logs greppable when redirected).
if [ -t 1 ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  CYAN='\033[0;36m'
  NC='\033[0m'
else
  RED='' GREEN='' YELLOW='' CYAN='' NC=''
fi

OPEN=0
DASHBOARD_PORT=3000
DAEMON_HOST=127.0.0.1
DAEMON_PORT=8472
DAEMON_EXTRA=()

usage() {
  cat <<'EOF'
Usage: ./run.sh [options]

Starts the Loom OS daemon and Next.js dashboard together.
Ctrl+C stops both (including Next.js child processes).

Launcher options:
  --open                 Open http://localhost:<dashboard-port> when ready
  --dashboard-port PORT  Dashboard port (default: 3000)
  -h, --help             Show this help

Passed through to `loom start`:
  --host HOST            Bind host (default: 127.0.0.1)
  --port PORT            Daemon port (default: 8472)
  --reload               Enable uvicorn auto-reload
  --log-level LEVEL      Log level (default: info)
  --auth-token TOKEN     Enable team mode with token auth
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --open)
      OPEN=1
      shift
      ;;
    --dashboard-port)
      DASHBOARD_PORT="${2:?--dashboard-port requires a value}"
      shift 2
      ;;
    --host)
      DAEMON_HOST="${2:?--host requires a value}"
      shift 2
      ;;
    --port)
      DAEMON_PORT="${2:?--port requires a value}"
      shift 2
      ;;
    --reload)
      DAEMON_EXTRA+=(--reload)
      shift
      ;;
    --log-level)
      DAEMON_EXTRA+=(--log-level "${2:?--log-level requires a value}")
      shift 2
      ;;
    --auth-token)
      DAEMON_EXTRA+=(--auth-token "${2:?--auth-token requires a value}")
      shift 2
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}" >&2
      usage >&2
      exit 1
      ;;
  esac
done

kill_tree() {
  local pid=$1
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  for child in $children; do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

CLEANED=0
cleanup() {
  [ "$CLEANED" -eq 1 ] && return
  CLEANED=1
  echo ""
  echo "Shutting down..."
  if [ -n "${DASHBOARD_PID:-}" ]; then
    kill_tree "$DASHBOARD_PID"
  fi
  if [ -n "${DAEMON_PID:-}" ]; then
    kill_tree "$DAEMON_PID"
  fi
  wait 2>/dev/null || true
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
# shellcheck source=/dev/null
source "$PROJECT_ROOT/.venv/bin/activate"

# --------------- daemon deps ---------------
if ! command -v loom &>/dev/null; then
  echo -e "${YELLOW}Installing daemon (pip install -e \".[dev]\")...${NC}"
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
DAEMON_URL="http://${DAEMON_HOST}:${DAEMON_PORT}"
DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}"

echo ""
echo -e "${GREEN}=== Loom OS ===${NC}"
echo -e "Daemon    → ${CYAN}${DAEMON_URL}${NC}"
echo -e "Dashboard → ${CYAN}${DASHBOARD_URL}${NC}"
echo "Press Ctrl+C to stop."
echo ""

cd "$PROJECT_ROOT"
loom start --host "$DAEMON_HOST" --port "$DAEMON_PORT" ${DAEMON_EXTRA[@]+"${DAEMON_EXTRA[@]}"} &
DAEMON_PID=$!

wait_for_health() {
  local url="${DAEMON_URL}/api/health"
  local i=0
  while [ "$i" -lt 40 ]; do
    if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
      return 1
    fi
    if python - "$url" <<'PY'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=1) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
    then
      return 0
    fi
    sleep 0.25
    i=$((i + 1))
  done
  return 1
}

if wait_for_health; then
  echo -e "${GREEN}[daemon]${NC} ready at ${DAEMON_URL} (pid=${DAEMON_PID})"
else
  echo -e "${RED}Daemon failed to become healthy at ${DAEMON_URL}/api/health${NC}"
  exit 1
fi

cd "$PROJECT_ROOT/dashboard"
npm run dev -- -p "$DASHBOARD_PORT" &
DASHBOARD_PID=$!
cd "$PROJECT_ROOT"

sleep 2
if ! kill -0 "$DASHBOARD_PID" 2>/dev/null; then
  echo -e "${RED}Dashboard failed to start. Check logs above for errors.${NC}"
  exit 1
fi
echo -e "${GREEN}[dashboard]${NC} starting at ${DASHBOARD_URL} (pid=${DASHBOARD_PID})"

if [ "$OPEN" -eq 1 ]; then
  if command -v open &>/dev/null; then
    open "$DASHBOARD_URL" >/dev/null 2>&1 || true
  elif command -v xdg-open &>/dev/null; then
    xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 || true
  else
    echo -e "${YELLOW}--open requested but no browser opener found; visit ${DASHBOARD_URL}${NC}"
  fi
fi

# Block until either process exits (bash 3.2 compat — no wait -n)
wait "$DAEMON_PID" "$DASHBOARD_PID" 2>/dev/null || true
