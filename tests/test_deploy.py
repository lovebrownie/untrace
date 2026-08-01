import sys

import pytest

from untrace import injector

_linux_only = pytest.mark.skipif(sys.platform == "win32", reason="Linux deploy paths")


@_linux_only
def test_user_deploy_roots_includes_sudo_user(monkeypatch, tmp_path):
    carlos_home = tmp_path / "carlos"
    root_home = tmp_path / "root"
    carlos_home.mkdir()
    root_home.mkdir()
    monkeypatch.setattr(
        injector,
        "home_dirs_to_search",
        lambda: [root_home, carlos_home],
    )

    roots = injector.user_deploy_roots()
    assert carlos_home / ".local" / "share" / "untrace" in roots
    assert root_home / ".local" / "share" / "untrace" in roots


@_linux_only
def test_remove_user_deploys_deletes_sudo_user_tree(monkeypatch, tmp_path):
    carlos_home = tmp_path / "carlos"
    root_home = tmp_path / "root"
    deploy = carlos_home / ".local" / "share" / "untrace"
    deploy.mkdir(parents=True)
    (deploy / "chrome").write_text("#!/bin/bash\n")
    (deploy / "extension" / "manifest.json").parent.mkdir(parents=True)
    (deploy / "extension" / "manifest.json").write_text("{}")

    monkeypatch.setattr(
        injector,
        "home_dirs_to_search",
        lambda: [root_home, carlos_home],
    )

    removed = injector.remove_user_deploys()
    assert deploy in removed
    assert not deploy.exists()


def test_get_untrace_root_prefers_user_deploy(monkeypatch, tmp_path):
    user_root = tmp_path / "user-untrace"
    user_root.mkdir()
    (user_root / "seed_profile.py").write_text("# stub\n")
    monkeypatch.setattr(injector, "USER_UNTRACE_ROOT", user_root)
    monkeypatch.setattr(injector, "user_deploy_roots", lambda: [user_root])
    injector.clear_untrace_root_override()

    assert injector.get_untrace_root() == user_root
