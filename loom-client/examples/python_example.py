"""Example: using loom-client with Claude Code or any Python agent."""
from loom_client import LoomClient

client = LoomClient()

# Register your agent
client.register(
    project="my-web-app",
    agent="claude-code",
    project_path="/Users/me/projects/my-web-app",
    capabilities=["code-analysis", "review", "testing"],
)

# Send a heartbeat
client.heartbeat(project="my-web-app", agent="claude-code", status="working")

# Drop a finding
client.finding(
    project="my-web-app",
    agent="claude-code",
    title="Auth service uses weak hashing",
    body="The AuthService class uses MD5 for password hashing. Should use bcrypt.",
    files=["src/auth/service.py"],
    type="bug-report",
)

# Dispatch a task to another agent
client.task(
    project="my-web-app",
    title="Fix auth hashing",
    instruction="Replace MD5 with bcrypt in src/auth/service.py",
    target_agent="codex",
    priority="high",
)

print("✓ All inbox files written to ~/.loom/inbox/my-web-app/")