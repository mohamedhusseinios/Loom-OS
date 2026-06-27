import daemon.supervisor as sup_mod
from daemon.supervisor import WorkerSupervisor


class _FakePopen:
    def __init__(self, cmd):
        self.cmd = cmd
        self._returncode = None  # None = still running
        self.terminated = False
        self.killed = False
    def poll(self):
        return self._returncode
    def terminate(self):
        self.terminated = True
        self._returncode = -15
    def kill(self):
        self.killed = True
        self._returncode = -9
    def wait(self, timeout=None):
        return self._returncode


def _patch_popen(monkeypatch, sink=None):
    def _factory(cmd, *a, **k):
        p = _FakePopen(cmd)
        if sink is not None:
            sink.append(p)
        return p
    monkeypatch.setattr(sup_mod.subprocess, "Popen", _factory)


def test_spawn_tracks_process_and_builds_once_command(monkeypatch):
    created = []
    _patch_popen(monkeypatch, created)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1", 5.0)
    assert s.is_running("t1") is True
    assert s.running_ids() == ["t1"]
    cmd = created[0].cmd
    assert cmd[1:4] == ["-m", "daemon.main", "worker"]
    assert "--once" in cmd
    assert cmd[cmd.index("--task") + 1] == "t1"
    assert cmd[cmd.index("--project-path") + 1] == "/tmp/noor"


def test_spawn_idempotent_while_running(monkeypatch):
    _patch_popen(monkeypatch)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    first = s._procs["t1"]
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    assert s._procs["t1"] is first


def test_is_running_reaps_exited(monkeypatch):
    _patch_popen(monkeypatch)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    s._procs["t1"]._returncode = 0  # simulate exit
    assert s.is_running("t1") is False
    assert "t1" not in s._procs
    assert s.running_ids() == []


def test_stop_terminates_live_process(monkeypatch):
    _patch_popen(monkeypatch)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    proc = s._procs["t1"]
    assert s.stop("t1") is True
    assert proc.terminated is True
    assert s.is_running("t1") is False
    assert s.stop("t1") is False  # nothing left to stop


class _StubbornPopen:
    """A process that ignores terminate() and times out, forcing kill()."""
    def __init__(self, cmd):
        self.cmd = cmd
        self._returncode = None
        self.killed = False
        self.waited_after_kill = False
    def poll(self):
        return self._returncode
    def terminate(self):
        pass  # ignores SIGTERM — stays live
    def kill(self):
        self.killed = True
        self._returncode = -9
    def wait(self, timeout=None):
        if timeout is not None and not self.killed:
            raise sup_mod.subprocess.TimeoutExpired(self.cmd, timeout)
        self.waited_after_kill = True
        return self._returncode


def test_stop_kills_and_reaps_on_timeout(monkeypatch):
    _patch_popen(monkeypatch)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    stub = _StubbornPopen(["x"])
    s._procs["t1"] = stub
    assert s.stop("t1") is True
    assert stub.killed is True
    assert stub.waited_after_kill is True   # proc.wait() reaped the process after kill()
    assert s.is_running("t1") is False
