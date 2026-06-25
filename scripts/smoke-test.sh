#!/bin/bash
# scripts/smoke-test.sh — end-to-end test for Agentic OS

set -e

AGENTIC_OS_HOME="$HOME/.agentic-os"
INBOX="$AGENTIC_OS_HOME/inbox/test-project"
API="http://localhost:8472"

echo "=== Agentic OS Smoke Test ==="

# 1. Start daemon in background
echo "[1/5] Starting daemon..."
cd "$(dirname "$0")/.."
source .venv/bin/activate
agentic-os --port 8472 &
DAEMON_PID=$!
sleep 3

# 2. Health check
echo "[2/5] Health check..."
curl -s "$API/api/health" | grep '"status":"ok"'

# 3. Register an agent
echo "[3/5] Registering test agent..."
mkdir -p "$INBOX"
cat > "$INBOX/register.json" << 'EOF'
{
  "agent": "test-agent",
  "version": "1.0.0",
  "project": "test-project",
  "project_path": "/tmp/test-project",
  "capabilities": ["testing"]
}
EOF
sleep 1

# 4. Check project appears
echo "[4/5] Checking project list..."
curl -s "$API/api/projects" | grep "test-project"

# 5. Send heartbeat
echo "[5/5] Sending heartbeat..."
cat > "$INBOX/heartbeat.json" << EOF
{
  "agent": "test-agent",
  "project": "test-project",
  "status": "smoke testing",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
sleep 1

# Check agent appears
curl -s "$API/api/projects/test-project/agents" | grep "test-agent"

# Cleanup
kill $DAEMON_PID 2>/dev/null || true
echo ""
echo "=== All smoke tests passed! ==="
