import daemon.worker as worker_mod
from daemon.worker import Worker, ClaudeResult


def _worker(**kw):
    return Worker(
        project="noor", agent="claude-code",
        project_path="/tmp/noor", base_url="http://x", **kw,
    )


class _CaptureWorker(Worker):
    """Captures PATCH/finding/progress instead of doing real I/O."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.patches = []
        self.findings = []
        self.progress = []
    def _patch_task(self, task_id, body):
        self.patches.append((task_id, body)); return {}
    def _post_progress(self, task_id, message):
        self.progress.append((task_id, message))
    def _write_finding(self, task_id, title, text):
        self.findings.append((task_id, title, text))


def _patch_git_and_claude(monkeypatch, claude_result):
    monkeypatch.setattr(worker_mod, "current_branch", lambda repo: "main")
    monkeypatch.setattr(worker_mod, "create_worktree", lambda *a, **k: None)
    monkeypatch.setattr(worker_mod, "commit_all", lambda *a, **k: True)
    monkeypatch.setattr(worker_mod, "run_claude", lambda *a, **k: claude_result)


def test_process_task_success_marks_done_and_writes_finding(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor", base_url="http://x")
    _patch_git_and_claude(monkeypatch, ClaudeResult("did the work", "sess-1", False))

    w.process_task({"id": "t1", "title": "Fix bug", "instruction": "fix it",
                    "acceptance_criteria": "", "result": None})

    final = w.patches[-1]
    assert final[0] == "t1"
    assert final[1]["status"] == "done"
    body = __import__("json").loads(final[1]["result"])
    assert body["session_id"] == "sess-1"
    assert body["branch"] == "loom/task-t1"
    assert body["base_branch"] == "main"
    assert body["summary"] == "did the work"
    assert w.findings and w.findings[0][2] == "did the work"


def test_process_task_claude_error_marks_blocked(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor", base_url="http://x")
    _patch_git_and_claude(monkeypatch, ClaudeResult("boom", "sess-2", True))

    w.process_task({"id": "t2", "title": "T", "instruction": "x",
                    "acceptance_criteria": "", "result": None})

    assert w.patches[-1][1]["status"] == "blocked"
    assert w.findings == []  # no finding on failure


def test_process_task_worktree_failure_marks_blocked(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor", base_url="http://x")
    monkeypatch.setattr(worker_mod, "current_branch", lambda repo: "main")
    def _boom(*a, **k):
        raise RuntimeError("not a git repo")
    monkeypatch.setattr(worker_mod, "create_worktree", _boom)

    w.process_task({"id": "t3", "title": "T", "instruction": "x", "result": None})
    assert w.patches[-1][1]["status"] == "blocked"
    assert "not a git repo" in w.patches[-1][1]["result"]


def test_agent_id_matches_daemon_convention():
    assert _worker().agent_id == "claude-code-noor"


def test_eligible_filters_by_assignee_and_inflight():
    w = _worker()
    tasks = [
        {"id": "1", "assignee": "claude-code-noor"},
        {"id": "2", "assignee": "someone-else"},
        {"id": "3", "assignee": "claude-code-noor"},
    ]
    w._inflight.add("3")
    eligible = w.eligible(tasks)
    assert [t["id"] for t in eligible] == ["1"]


def test_claude_result_fields():
    r = ClaudeResult(text="ok", session_id=None, is_error=False)
    assert r.text == "ok"
    assert r.session_id is None
    assert r.is_error is False


def test_poll_once_processes_one_eligible_task(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor")
    monkeypatch.setattr(
        w, "_get_running_tasks",
        lambda: [
            {"id": "a", "assignee": "claude-code-noor", "title": "A", "instruction": "x", "result": None},
            {"id": "b", "assignee": "other", "title": "B", "instruction": "y", "result": None},
        ],
    )
    processed = []
    monkeypatch.setattr(w, "process_task", lambda task: processed.append(task["id"]))

    w.poll_once()
    assert processed == ["a"]  # only the assigned one, one at a time


# ---------------------------------------------------------------------------
# ensure_registered dedup tests
# ---------------------------------------------------------------------------

class _RegWorker(Worker):
    def __init__(self, existing, **kw):
        super().__init__(**kw)
        self._existing = existing
        self.posts = []

    def _api(self, method, path, body=None):
        if method == "GET" and path.endswith("/agents"):
            return {"agents": self._existing}
        if method == "POST":
            self.posts.append((path, body))
        return {}


def test_ensure_registered_skips_when_already_registered():
    w = _RegWorker(
        [{"agent_id": "claude-code-noor"}],
        project="noor", agent="claude-code", project_path="/tmp/noor", base_url="http://x",
    )
    w.ensure_registered()
    assert w.posts == []  # already present → no register POST


def test_ensure_registered_registers_when_absent():
    w = _RegWorker(
        [],
        project="noor", agent="claude-code", project_path="/tmp/noor", base_url="http://x",
    )
    w.ensure_registered()
    assert len(w.posts) == 1
    assert "register-agent" in w.posts[0][0]
