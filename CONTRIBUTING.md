# Contributing to Loom OS

Thank you for your interest in contributing to Loom OS! This guide covers how to set up the project locally, run tests, and submit changes.

## Prerequisites

- Python 3.11 or later
- Node.js 20 or later
- Git

## Running the Daemon

The daemon is a FastAPI + uvicorn server that runs on `http://127.0.0.1:8472`.

```bash
# Set up the Python environment
python3 -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate

# Install dependencies (including dev tools)
pip install -e ".[dev]"

# Start the daemon
loom --port 8472
# or equivalently: loom start --port 8472
```

The daemon will watch `~/.loom/inbox/` for incoming agent files and serve REST + WebSocket APIs.

## Running the Dashboard

The dashboard is a Next.js app that runs on `http://localhost:3000` and talks to the daemon over REST + WebSocket.

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:3000 in your browser. **The daemon must be running for the dashboard to display data.**

## Running Tests

**Important:** Always use `python -m pytest` (not bare `pytest`). The `benchmarks` package is not installed into the venv, and bare `pytest` will fail to collect `tests/test_benchmarks.py`.

```bash
# Run the full test suite
python -m pytest tests/ -v

# Run a specific test module
python -m pytest tests/test_api.py -v

# Run a specific test
python -m pytest tests/test_api.py::test_health -v

# Run smoke tests (end-to-end: daemon + agent + API)
bash scripts/smoke-test.sh
```

For the dashboard, run the linter:

```bash
cd dashboard
npm run lint
```

## Important: Daemon Restart Gotcha

**After editing any file in `daemon/*.py`, you must restart the daemon before testing changes manually.** The daemon serves code in-memory; a stale process will cause phantom missing-feature or 404 errors that make it look like your change didn't work when it actually did.

Quick checklist:
1. Edit `daemon/some_file.py`
2. Stop the running daemon (Ctrl+C)
3. Restart: `loom --port 8472`
4. Verify your change in the dashboard or via curl

## Project Structure

- **`daemon/`** — FastAPI application; core logic (watcher, router, registry, graph engine, API, MCP server)
- **`dashboard/`** — Next.js frontend; graph visualization, agent management, task board
- **`docs/`** — User-facing and design documentation
  - **`docs/plans/`** — implementation plans (e.g., roadmap, feature plans)
  - **`docs/superpowers/specs/`** — design specifications (e.g., system architecture, feature designs)
- **`docs-site/`** — Markdown documentation site (built by `.github/workflows/docs.yml` and published to GitHub Pages)
- **`tests/`** — pytest test suite for the daemon
- **`benchmarks/`** — reproducible performance benchmarks

## Commit Hygiene

Use conventional commits (e.g., `feat:`, `fix:`, `docs:`, `test:`). When committing changes:

```bash
# Stage only the files you've changed — avoid sweeping .omc/ churn
git add path/to/file1.py path/to/file2.py

# Commit with a conventional message
git commit -m "feat: add new capability

Description of why and what.

Co-Authored-By: Your Name <your.email@example.com>"
```

## Documentation

- **User guide & architecture** — [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- **Filesystem protocol** — [docs/FILESYSTEM-PROTOCOL.md](docs/FILESYSTEM-PROTOCOL.md)
- **API reference** — [docs/API.md](docs/API.md)
- **Design specs** — [docs/superpowers/specs/](docs/superpowers/specs/)
- **Implementation plans** — [docs/plans/](docs/plans/)
- **Published docs site** — GitHub Pages (built on merge to main; source is `docs-site/`)

## Community

- **GitHub Discussions** — Ask questions, share ideas, and discuss the project ([enable in repo settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/enabling-or-disabling-github-discussions))
- **Design & planning** — See [docs/plans/](docs/plans/) and [docs/superpowers/specs/](docs/superpowers/specs/) for active roadmap and feature designs

## Reporting Issues

Before opening an issue, check:
1. Does the daemon need to be restarted after your edits?
2. Are you using `python -m pytest` (not bare `pytest`)?
3. Is the daemon running on `:8472` and the dashboard on `:3000`?

Include:
- Steps to reproduce
- Expected vs. actual behavior
- Relevant logs (check `~/.loom/daemon.log`)
- Your Python and Node versions

---

**Thank you for contributing to Loom OS!**
