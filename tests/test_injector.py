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
def test_remove_clears_extension(temp_untrace):
    _, ext_dir, script_path = temp_untrace
    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)
    injector.remove()

    assert not ext_dir.exists()
    assert script_path.is_file()
    assert not injector.is_installed()


@_linux_only
def test_setup_does_not_force_install_extension(temp_untrace, monkeypatch, tmp_path):
    policy_file = tmp_path / "policies" / "managed" / "untrace.json"
    external_dirs = [
        tmp_path / "opt-google-chrome-extensions",
        tmp_path / "usr-share-google-chrome-extensions",
    ]
    monkeypatch.setattr(injector, "LINUX_CHROME_POLICY_DIR", policy_file.parent)
    monkeypatch.setattr(injector, "LINUX_CHROME_POLICY_FILE", policy_file)
    monkeypatch.setattr(injector, "LINUX_CHROME_EXTERNAL_DIRS", external_dirs)
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)

    assert not policy_file.exists()
    for ext_dir_path in external_dirs:
        assert not ext_dir_path.exists() or not any(ext_dir_path.iterdir())


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


@_linux_only
def test_seed_profile_script_seeds_extra_load_extension_paths(temp_untrace, tmp_path):
    import base64
    import hashlib
    import subprocess

    root, _, _ = temp_untrace
    injector.setup(list(DEFAULT_CHROME_SCRIPTS), CHROME_SCRIPTS)

    key_bytes = b"\x00" * 162
    key_b64 = base64.b64encode(key_bytes).decode()
    extra = tmp_path / "nopecha"
    extra.mkdir()
    (extra / "manifest.json").write_text(
        json.dumps(
            {
                "name": "NopeCHA",
                "version": "0.6.1",
                "manifest_version": 3,
                "key": key_b64,
            }
        )
    )

    profile = tmp_path / "profile"
    script = root / "seed_profile.py"
    subprocess.run(
        [sys.executable, str(script), str(profile), str(extra)],
        check=True,
        capture_output=True,
        text=True,
    )

    digest = hashlib.sha256(key_bytes).digest()
    extra_id = "".join(
        chr(ord("a") + (digest[i] >> 4)) + chr(ord("a") + (digest[i] & 0x0F))
        for i in range(16)
    )
    prefs = json.loads((profile / "Default" / "Preferences").read_text())
    assert injector.extension_id() in prefs["extensions"]["settings"]
    assert extra_id in prefs["extensions"]["settings"]
    assert (profile / "Default" / "Extensions" / extra_id / "0.6.1").is_dir()


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
