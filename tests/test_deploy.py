from pathlib import Path

from untrace import injector
from untrace.__main__ import deploy_linux


def test_deploy_writes_user_extension(monkeypatch, tmp_path):
    user_root = tmp_path / "user-untrace"
    monkeypatch.setattr(injector, "USER_UNTRACE_ROOT", user_root)
    injector.use_user_root()

    deploy_linux(stealth=True, flags=True)

    assert (user_root / "extension" / "manifest.json").is_file()
    assert (user_root / "seed_profile.py").is_file()
    assert (user_root / "chrome").is_file()
    assert injector.get_untrace_root() == user_root


def test_get_untrace_root_prefers_user_deploy(monkeypatch, tmp_path):
    user_root = tmp_path / "user-untrace"
    user_root.mkdir()
    (user_root / "seed_profile.py").write_text("# stub\n")
    monkeypatch.setattr(injector, "USER_UNTRACE_ROOT", user_root)
    injector.clear_untrace_root_override()

    assert injector.get_untrace_root() == user_root