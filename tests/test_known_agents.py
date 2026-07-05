"""Tests for the built-in agent catalog and detection helpers."""
from daemon.known_agents import detect_installed, get_known_agents


def _make_fake_path(exists_at: str, home: str = "/Users/test"):
    class FakePath:
        def __init__(self, path):
            self._path = str(path)

        def __str__(self):
            return self._path

        def __fspath__(self):
            return self._path

        def exists(self):
            return self._path == exists_at

        def __truediv__(self, other):
            sep = "" if self._path.endswith("/") else "/"
            return FakePath(f"{self._path}{sep}{other}")

        @classmethod
        def home(cls):
            return FakePath(home)

    return FakePath


def test_catalog_includes_kimi_code_and_zcode():
    names = {a["name"] for a in get_known_agents()}
    assert "kimi-code" in names
    assert "zcode" in names


def test_kimi_code_detected_when_kimi_binary_on_path(monkeypatch):
    def fake_which(name: str):
        return "/usr/local/bin/kimi" if name == "kimi" else None

    monkeypatch.setattr("daemon.known_agents.shutil.which", fake_which)
    installed = detect_installed()
    assert installed.get("kimi-code") == "/usr/local/bin/kimi"


def test_zcode_detected_when_macos_app_bundle_present(monkeypatch):
    monkeypatch.setattr(
        "daemon.known_agents.Path",
        _make_fake_path("/Applications/ZCode.app"),
    )
    installed = detect_installed()
    assert installed.get("zcode") == "/Applications/ZCode.app"


def test_zcode_detected_in_user_applications_folder(monkeypatch):
    home = "/Users/test"
    monkeypatch.setattr(
        "daemon.known_agents.Path",
        _make_fake_path(f"{home}/Applications/ZCode.app", home=home),
    )
    installed = detect_installed()
    assert installed.get("zcode") == f"{home}/Applications/ZCode.app"


def test_cursor_detected_via_app_bundle(monkeypatch):
    monkeypatch.setattr(
        "daemon.known_agents.Path",
        _make_fake_path("/Applications/Cursor.app"),
    )
    installed = detect_installed()
    assert installed.get("cursor") == "/Applications/Cursor.app"


def test_kimi_code_not_detected_without_binary(monkeypatch):
    monkeypatch.setattr("daemon.known_agents.shutil.which", lambda _name: None)
    installed = detect_installed()
    assert "kimi-code" not in installed


def test_zcode_not_detected_without_app_bundle(monkeypatch):
    monkeypatch.setattr(
        "daemon.known_agents.Path",
        _make_fake_path(exists_at=""),
    )
    installed = detect_installed()
    assert "zcode" not in installed
