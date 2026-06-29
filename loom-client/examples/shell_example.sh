#!/bin/bash
# Example: using the inbox protocol directly from shell (no SDK needed)
# The SDK is a convenience — the raw-file path always works.

INBOX="$HOME/.loom/inbox/my-project"
mkdir -p "$INBOX"

# Register
cat > "$INBOX/register.json" << 'EOF'
{"agent": "claude-code", "version": "1.0", "project": "my-project", "project_path": "/Users/me/projects/my-project", "capabilities": ["code-analysis"]}
EOF

# Finding
cat > "$INBOX/finding-auth-review.md" << 'EOF'
---
agent: claude-code
project: my-project
type: code-analysis
files:
  - src/auth.py
---
The AuthService class handles login via BcryptHasher. Looks solid.
EOF

echo "Files written to $INBOX"
echo "The Loom daemon will pick these up automatically."