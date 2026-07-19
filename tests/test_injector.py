import json
import os
import sys

import pytest

from untrace import injector
from untrace.__main__ import CHROME_SCRIPTS, DEFAULT_CHROME_SCRIPTS

_linux_only = pytest.mark.skipif(sys.platform == "win32", reason="Linux-only")


@pytest.fixture
def temp_untrace(monkeypatch, tmp_path):
    root = tmp_path / "untrace"
    ext_dir = root / "extension"
    script_path = root / "custom.js"
    monkeypatch.setattr(injector, "UNTRACE_ROOT", root)
    monkeypatch.setattr(injector, "EXTENSION_DIR", ext_dir)
    monkeypatch.setattr(injector, "CUSTOM_SCRIPT_PATH", script_path)
    monkeypatch.setattr(injector, "EXTENSION_KEY_PATH", root / "extension.pem")
    monkeypatch.setattr(injector, "EXTENSION_CRX_PATH", root / "extension.crx")
    monkeypatch.setattr(injector, "EXTENSION_UPDATES_XML", root / "updates.xml")
    monkeypatch.setattr(injector, "SEED_PROFILE_SCRIPT", root / "seed_profile.py")
    return root, ext_dir, script_path


@_linux_only
def test_setup_creates_extension(temp_untrace):
    root, ext_dir, script_path = temp_untrace
    scripts = list(DEFAULT_CHROME_SCRIPTS)

    result = injector.setup(scripts, CHROME_SCRIPTS)

    assert result == script_path
    assert (root / "seed_profile.py").is_file()
    assert (ext_dir / "manifest.json").is_file()
    assert (ext_dir / "js" / "utils.js").is_file()
    assert (ext_dir / "js" / "navigator.webdriver.js").is_file()
    assert (ext_dir / "icons" / "icon-128.png").is_file()
    manifest = json.loads((ext_dir / "manifest.json").read_text())
    assert manifest["icons"]["128"] == "icons/icon-128.png"
    assert injector.is_installed()


@_linux_only
def test_manifest_runs_at_document_start(temp_untrace):
    _, ext_dir, _ = temp_untrace
    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)

    manifest = json.loads((ext_dir / "manifest.json").read_text())
    script = manifest["content_scripts"][0]
    assert script["run_at"] == "document_start"
    assert script["matches"] == ["<all_urls>"]
    assert script["world"] == "MAIN"
    assert script["all_frames"] is True
    assert script["js"][0] == "js/utils.js"
    assert "js/navigator.webdriver.js" in script["js"]


def test_extension_version_is_valid_for_chrome():
    from untrace import __version__

    version = injector._extension_version()
    assert version == __version__
    parts = version.split(".")
    assert 1 <= len(parts) <= 4
    for part in parts:
        assert part.isdigit()
        assert 0 <= int(part) <= 65536


@_linux_only
def test_pack_extension_crx_adds_no_sandbox_when_root(temp_untrace, monkeypatch):
    _, ext_dir, _ = temp_untrace
    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        (ext_dir.parent / "extension.crx").write_text("packed")

    monkeypatch.setattr(injector.subprocess, "run", fake_run)
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    injector._pack_extension_crx(chrome_real="/usr/bin/false")

    assert "--no-sandbox" in captured["cmd"]
    assert f"--pack-extension={ext_dir}" in captured["cmd"]


@_linux_only
def test_remove_clears_extension(temp_untrace):
    _, ext_dir, script_path = temp_untrace
    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)
    injector.remove()

    assert not ext_dir.exists()
    assert script_path.is_file()
    assert not injector.is_installed()


@pytest.fixture
def temp_registration(monkeypatch, tmp_path):
    root = tmp_path / "untrace"
    ext_dir = root / "extension"
    crx_path = root / "extension.crx"
    updates_path = root / "updates.xml"
    policy_file = root / "policies" / "managed" / "untrace.json"
    external_dirs = [
        root / "opt-google-chrome-extensions",
        root / "usr-share-google-chrome-extensions",
    ]

    monkeypatch.setattr(injector, "UNTRACE_ROOT", root)
    monkeypatch.setattr(injector, "EXTENSION_DIR", ext_dir)
    monkeypatch.setattr(injector, "CUSTOM_SCRIPT_PATH", root / "custom.js")
    monkeypatch.setattr(injector, "EXTENSION_KEY_PATH", root / "extension.pem")
    monkeypatch.setattr(injector, "EXTENSION_CRX_PATH", crx_path)
    monkeypatch.setattr(injector, "EXTENSION_UPDATES_XML", updates_path)
    monkeypatch.setattr(injector, "SEED_PROFILE_SCRIPT", root / "seed_profile.py")
    monkeypatch.setattr(injector, "LINUX_CHROME_POLICY_DIR", policy_file.parent)
    monkeypatch.setattr(injector, "LINUX_CHROME_POLICY_FILE", policy_file)
    monkeypatch.setattr(injector, "LINUX_CHROME_EXTERNAL_DIRS", external_dirs)

    fake_pubkey_b64 = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAq42dTgptg7Xs8zG6VVRVNu75ltwqSwFFXKQCQS3Ho8An/9xEAbIgw0+3l4+lD9gDbdm/XES+J+abFlXxswIDtXK0V/xO5HJSS4DfKzfuRPi4kwSMI6CboqpShUFEl/HAWSP7pNjo0EIZ9eh9bkCDNbvZGtecMdIyMm0hcA8zJ8PCyJTojSMomydvgw0E5Bn4URJS8GjpcoyK+T1ibmyZY+r+CJsOt92/iJ5Ckfs7UaLfX+rDIDe/ygwbS2zw97fsCSJHlUEUStmD8zhhi6gG0U6swa0h/JEOGD3DpA0TtOfVmfogA8jP3HLAJGbC5Iimdag12slPwlD1GQyrDtewfwIDAQAB"
    monkeypatch.setattr(injector, "_public_key_base64", lambda: fake_pubkey_b64)
    monkeypatch.setattr(injector, "_ensure_extension_private_key", lambda: None)
    root.mkdir(parents=True, exist_ok=True)
    (root / "extension.pem").touch()

    return {
        "ext_dir": ext_dir,
        "crx_path": crx_path,
        "updates_path": updates_path,
        "policy_file": policy_file,
        "external_dirs": external_dirs,
        "expected_id": injector.extension_id_from_public_key(fake_pubkey_b64),
    }


@_linux_only
def test_setup_does_not_force_install_extension(temp_registration, monkeypatch):
    data = temp_registration

    monkeypatch.setattr(
        injector,
        "_pack_extension_crx",
        lambda _chrome_real=None: data["crx_path"].write_text("DUMMY CRX"),
    )
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)

    assert not data["policy_file"].exists()
    for ext_dir_path in data["external_dirs"]:
        assert not (ext_dir_path / f"{data['expected_id']}.json").exists()
    assert not injector.is_fully_registered()


@_linux_only
def test_register_system_extension(temp_registration, monkeypatch):
    data = temp_registration
    expected_id = data["expected_id"]

    monkeypatch.setattr(
        injector,
        "_pack_extension_crx",
        lambda _chrome_real=None: data["crx_path"].write_text("DUMMY CRX"),
    )
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)
    injector.register_system_extension()

    policy = json.loads(data["policy_file"].read_text())
    assert (
        policy["ExtensionSettings"][expected_id]["installation_mode"]
        == "force_installed"
    )
    for ext_dir_path in data["external_dirs"]:
        reg = json.loads((ext_dir_path / f"{expected_id}.json").read_text())
        assert reg["external_crx"] == str(data["crx_path"])
    assert injector.is_fully_registered()


@_linux_only
def test_unregister_clears_registration_files(temp_registration, monkeypatch):
    data = temp_registration
    expected_id = data["expected_id"]

    monkeypatch.setattr(
        injector,
        "_pack_extension_crx",
        lambda _chrome_real=None: data["crx_path"].write_text("DUMMY"),
    )
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)
    injector.register_system_extension()
    injector.remove()

    assert not data["crx_path"].exists()
    assert not data["policy_file"].exists()
    for ext_dir_path in data["external_dirs"]:
        assert not (ext_dir_path / f"{expected_id}.json").exists()
    assert not injector.is_fully_registered()


@_linux_only
def test_seed_extension_into_profile(temp_untrace):
    _, ext_dir, _ = temp_untrace
    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)

    profile = temp_untrace[0] / "chrome_profile"
    injector.seed_extension_into_profile(profile)

    manifest = json.loads((ext_dir / "manifest.json").read_text())
    ext_id = injector.extension_id()
    seeded = profile / "Default" / "Extensions" / ext_id / manifest["version"]
    assert seeded.is_dir()

    prefs = json.loads((profile / "Default" / "Preferences").read_text())
    assert (
        prefs["extensions"]["settings"][ext_id]["location"]
        == injector.LOCATION_UNPACKED
    )
    assert prefs["extensions"]["ui"]["developer_mode"] is True


def test_pack_extension_zip_for_webstore(temp_untrace, tmp_path):
    out = tmp_path / "untrace-injector.zip"
    path = injector.pack_extension_zip(
        out,
        list(DEFAULT_CHROME_SCRIPTS),
        CHROME_SCRIPTS,
        version="9.8.7",
    )
    assert path == out.resolve()
    assert out.is_file()

    import zipfile

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert any(n.startswith("js/") and n.endswith(".js") for n in names)
        assert "icons/icon-16.png" in names
        assert "icons/icon-48.png" in names
        assert "icons/icon-128.png" in names
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["version"] == "9.8.7"
    assert "key" not in manifest
    assert manifest["manifest_version"] == 3
    assert manifest["icons"] == {
        "16": "icons/icon-16.png",
        "48": "icons/icon-48.png",
        "128": "icons/icon-128.png",
    }
    assert manifest["action"]["default_icon"] == manifest["icons"]
