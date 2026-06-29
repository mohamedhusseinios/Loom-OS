"""Loom daemon entry point and CLI."""

import argparse
import json
import logging
import os
import sys
import uvicorn


def cmd_start(args):
    """Start the Loom daemon."""
    # Configure auth token if provided (team mode)
    if getattr(args, "auth_token", None):
        import os
        os.environ["LOOM_AUTH_TOKEN"] = args.auth_token
        from daemon.auth import configure_auth_token
        configure_auth_token(args.auth_token)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "daemon.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


def cmd_register(args):
    """Write a register.json to the inbox so an agent joins a project."""
    inbox_dir = os.path.expanduser(f"~/.loom/inbox/{args.project}")
    os.makedirs(inbox_dir, exist_ok=True)

    register_path = os.path.join(inbox_dir, "register.json")
    capabilities = args.capabilities.split(",") if args.capabilities else []

    payload = {
        "agent": args.agent,
        "version": args.version,
        "project": args.project,
        "project_path": os.path.expanduser(args.project_path),
        "capabilities": [c.strip() for c in capabilities if c.strip()],
    }

    with open(register_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"✓ Registered agent '{args.agent}' for project '{args.project}'")
    print(f"  Path:    {payload['project_path']}")
    print(f"  Version: {payload['version']}")
    if payload["capabilities"]:
        print(f"  Caps:    {', '.join(payload['capabilities'])}")
    print(f"\n  Wrote: {register_path}")
    print(f"  The daemon will pick this up and trigger a graph build.")


def cmd_unregister(args):
    """Remove an agent from a project."""
    inbox_dir = os.path.expanduser(f"~/.loom/inbox/{args.project}")
    register_path = os.path.join(inbox_dir, "register.json")

    # Write an empty-ish register with an "unregister" marker. The daemon
    # doesn't have an explicit unregister file type, but we can write a
    # file the watcher ignores and instead directly tell the API.
    # For the CLI, we print instructions to use the dashboard or API.
    print(f"To unregister agent '{args.agent}' from project '{args.project}':")
    print(f"  curl -X DELETE http://localhost:8472/api/projects/{args.project}/agents/{args.agent}-{args.project}")
    print(f"\nOr use the dashboard: open the project's Agents page and click the trash icon.")


def cmd_worker(args):
    """Run a Loom worker that executes Running tasks with Claude Code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    from daemon.worker import Worker
    w = Worker(
        project=args.project,
        agent=args.agent,
        project_path=os.path.expanduser(args.project_path),
        base_url=args.base_url,
        model=args.model,
        max_budget_usd=args.max_budget_usd,
        poll_interval=args.poll,
    )
    if args.once:
        if not args.task:
            raise SystemExit("--once requires --task <id>")
        w.run_once(args.task)
    else:
        w.run()


def cmd_detect_agents(_args):
    """List coding agents detected on this machine."""
    from daemon.known_agents import get_known_agents, detect_installed

    known = get_known_agents()
    installed = detect_installed()

    print("Coding agents detected on this machine:\n")
    found_any = False
    for agent in known:
        path = installed.get(agent["name"])
        if path:
            found_any = True
            print(f"  ✓ {agent['display']:<20} ({agent['name']})")
            print(f"         {path}")
            print(f"         {agent['description']}")
            print()
        else:
            print(f"  ✗ {agent['display']:<20} ({agent['name']}) — not detected")
            print(f"         {agent['description']}")
            print()

    if not found_any:
        print("  No coding agents detected. Install one of the above to get started.")
    else:
        print(f"To register a detected agent with a project:")
        for agent in known:
            if agent["name"] in installed:
                print(f"  loom register --agent {agent['name']} --project <project> --project-path <path>")


def cmd_init(args):
    """Bootstrap a project: create the inbox and a starter register.json."""
    inbox = os.path.expanduser(f"~/.loom/inbox/{args.project}")
    os.makedirs(inbox, exist_ok=True)
    payload = {
        "agent": args.agent, "version": "1.0", "project": args.project,
        "project_path": os.path.expanduser(args.project_path), "capabilities": [],
    }
    with open(os.path.join(inbox, "register.json"), "w") as f:
        json.dump(payload, f, indent=2)
    print(f"✓ Initialized Loom project '{args.project}'")
    print("  Next: run `loom start`, then open http://localhost:3000")


def main():
    # Backward-compat: if someone runs `loom --host 127.0.0.1` (no subcommand
    # but with start flags), silently insert "start" so they don't get the
    # confusing "invalid choice: '127.0.0.1'" error.
    # Don't intercept --help / -h — let the main parser show all subcommands.
    KNOWN_SUBCOMMANDS = {"start", "register", "unregister", "detect-agents", "worker", "init"}
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        pass
    elif len(sys.argv) > 1 and sys.argv[1] not in KNOWN_SUBCOMMANDS and not sys.argv[1].startswith("-"):
        # Unknown positional — print the normal error
        pass
    elif len(sys.argv) > 1 and sys.argv[1] not in KNOWN_SUBCOMMANDS:
        # First arg is a flag (e.g. --host) → treat as `loom start ...`
        sys.argv.insert(1, "start")

    parser = argparse.ArgumentParser(
        description="Loom OS — unified agent memory fabric"
    )
    sub = parser.add_subparsers(dest="command", help="sub-command")

    # ---- loom start ----
    start_p = sub.add_parser("start", help="Start the Loom daemon")
    start_p.add_argument("--host", default="127.0.0.1", help="Bind host")
    start_p.add_argument("--port", type=int, default=8472, help="Bind port")
    start_p.add_argument("--reload", action="store_true", help="Enable auto-reload")
    start_p.add_argument("--log-level", default="info", help="Log level")
    start_p.add_argument("--auth-token", default=None,
                         help="Enable team mode with token-based auth (optional)")
    start_p.set_defaults(func=cmd_start)

    # ---- loom register ----
    reg_p = sub.add_parser("register", help="Register a coding agent with a project")
    reg_p.add_argument("--agent", required=True, help="Agent name (e.g. claude-code, codex, hermes)")
    reg_p.add_argument("--project", required=True, help="Project identifier (e.g. my-project)")
    reg_p.add_argument("--project-path", required=True, help="Absolute path to the project directory")
    reg_p.add_argument("--version", default="1.0", help="Agent version (default: 1.0)")
    reg_p.add_argument("--capabilities", default="", help="Comma-separated capabilities (e.g. 'code-analysis,bug-finding')")
    reg_p.set_defaults(func=cmd_register)

    # ---- loom unregister ----
    unreg_p = sub.add_parser("unregister", help="Remove an agent from a project")
    unreg_p.add_argument("--agent", required=True, help="Agent name to remove")
    unreg_p.add_argument("--project", required=True, help="Project identifier")
    unreg_p.set_defaults(func=cmd_unregister)

    # ---- loom detect-agents ----
    detect_p = sub.add_parser("detect-agents", help="List coding agents detected on this machine")
    detect_p.set_defaults(func=cmd_detect_agents)

    # ---- loom worker ----
    worker_p = sub.add_parser("worker", help="Run a worker that executes Running tasks with Claude Code")
    worker_p.add_argument("--project", required=True, help="Project identifier")
    worker_p.add_argument("--agent", default="claude-code", help="Agent name (default: claude-code)")
    worker_p.add_argument("--project-path", required=True, help="Absolute path to the git project")
    worker_p.add_argument("--base-url", default="http://127.0.0.1:8472", help="Daemon base URL")
    worker_p.add_argument("--model", default=None, help="Claude model (optional)")
    worker_p.add_argument("--max-budget-usd", type=float, default=5.0, help="Max USD to spend per task")
    worker_p.add_argument("--poll", type=float, default=2.5, help="Poll interval seconds")
    worker_p.add_argument("--once", action="store_true",
                          help="Process a single task (with --task) and exit")
    worker_p.add_argument("--task", default=None,
                          help="Task id to process when --once is set")
    worker_p.set_defaults(func=cmd_worker)

    # ---- loom init ----
    init_p = sub.add_parser("init", help="Bootstrap a Loom project in the current directory")
    init_p.add_argument("--project", required=True, help="Project identifier")
    init_p.add_argument("--project-path", default=".", help="Path to the project (default: cwd)")
    init_p.add_argument("--agent", default="claude-code", help="Initial agent name")
    init_p.set_defaults(func=cmd_init)

    args = parser.parse_args()

    if not args.command:
        # Backward-compat: no subcommand → start the daemon.
        # Also handle the case where someone passes `loom --host ...` without
        # the `start` subcommand — argparse would have errored, so we intercept
        # before parsing and rewrite argv.
        cmd_start(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
