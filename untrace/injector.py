from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    UNTRACE_ROOT = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Untrace"
else:
    UNTRACE_ROOT = Path("/etc/untrace")

CUSTOM_SCRIPT_PATH = UNTRACE_ROOT / "custom.js"
EXTENSION_DIR = UNTRACE_ROOT / "extension"
EXTENSION_KEY_PATH = UNTRACE_ROOT / "extension.pem"
EXTENSION_CRX_PATH = UNTRACE_ROOT / "extension.crx"
EXTENSION_UPDATES_XML = UNTRACE_ROOT / "updates.xml"
SEED_PROFILE_SCRIPT = UNTRACE_ROOT / "seed_profile.py"
JS_SOURCE_DIR = Path(__file__).parent / "js"
UTILS_FILENAME = "utils.js"

LINUX_CHROME_POLICY_DIR = Path("/etc/opt/chrome/policies/managed")
LINUX_CHROME_POLICY_FILE = LINUX_CHROME_POLICY_DIR / "untrace.json"

LINUX_CHROME_EXTERNAL_DIRS: list[Path] = [
    Path("/opt/google/chrome/extensions"),
    Path("/usr/share/google-chrome/extensions"),
]

CHROME_REAL_LINUX = "/opt/google/chrome/chrome_real"

LOCATION_UNPACKED = 4

DEFAULT_CUSTOM_JS = """// Optional custom JavaScript — runs after all stealth evasions.
// Edit this file and restart Chrome to apply changes.
"""


def scripts_to_deploy(
    enabled_names: list[str],
    script_catalog: dict[str, tuple[str, list | None]],
) -> list[tuple[str, list | None]]:
    if not enabled_names:
        return []
    deployed: list[tuple[str, list | None]] = [(UTILS_FILENAME, None)]
    for name in enabled_names:
        filename, args = script_catalog[name]
        deployed.append((filename, args))
    return deployed


def is_installed() -> bool:
    return EXTENSION_DIR.is_dir() and (EXTENSION_DIR / "manifest.json").is_file()


def is_policy_registered() -> bool:
    if IS_WINDOWS:
        return False
    return LINUX_CHROME_POLICY_FILE.is_file()


def is_fully_registered() -> bool:
    if IS_WINDOWS:
        return False
    if not is_installed():
        return False
    if not LINUX_CHROME_POLICY_FILE.is_file() or not EXTENSION_CRX_PATH.is_file():
        return False
    try:
        ext_id = extension_id()
    except Exception:
        return False
    for ext_dir in LINUX_CHROME_EXTERNAL_DIRS:
        if not (ext_dir / f"{ext_id}.json").is_file():
            return False
    return True


def extension_id_from_public_key(public_key_b64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(public_key_b64)).digest()
    return "".join(
        chr(ord("a") + (digest[i] >> 4)) + chr(ord("a") + (digest[i] & 0x0F))
        for i in range(16)
    )


def extension_settings_entry(ext_id: str, manifest: dict, dest: Path) -> dict:
    install_time = str(int(time.time() * 1_000_000))
    return {
        "location": LOCATION_UNPACKED,
        "path": str(dest),
        "state": 1,
        "manifest": manifest,
        "was_installed_by_default": False,
        "was_installed_by_oem": False,
        "first_install_time": install_time,
    }


def extension_launch_flags() -> list[str]:
    return []


def _ensure_extension_private_key() -> None:
    if EXTENSION_KEY_PATH.is_file():
        return
    subprocess.run(
        ["openssl", "genrsa", "-out", str(EXTENSION_KEY_PATH), "2048"],
        check=True,
    )
    os.chmod(EXTENSION_KEY_PATH, 0o600)


def _public_key_base64() -> str:
    _ensure_extension_private_key()
    result = subprocess.run(
        [
            "openssl",
            "rsa",
            "-in",
            str(EXTENSION_KEY_PATH),
            "-pubout",
            "-outform",
            "DER",
        ],
        check=True,
        capture_output=True,
    )
    return base64.b64encode(result.stdout).decode("ascii")


def extension_id() -> str:
    return extension_id_from_public_key(_public_key_base64())


def _extension_version() -> str:
    ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    return (
        f"1.{(ts // (65536 * 65536)) % 65536}." f"{(ts // 65536) % 65536}.{ts % 65536}"
    )


def wrap_iife(source: str, args: list | None = None) -> str:
    source = source.strip()
    if args is not None:
        args_literal = ", ".join(json.dumps(a) for a in args)
        return f"({source})({args_literal});\n"
    return f"({source})();\n"


def build_manifest(
    script_files: list[str], public_key_b64: str, version: str = "1.0"
) -> dict:
    return {
        "manifest_version": 3,
        "name": "Untrace Injector",
        "version": version,
        "key": public_key_b64,
        "host_permissions": ["<all_urls>"],
        "content_scripts": [
            {
                "matches": ["<all_urls>"],
                "js": script_files,
                "run_at": "document_start",
                "all_frames": True,
                "world": "MAIN",
            }
        ],
    }


def _deploy_stealth_scripts(
    ext_js_dir: Path,
    enabled_scripts: list[str],
    script_catalog: dict[str, tuple[str, list | None]],
) -> list[str]:
    ext_js_dir.mkdir(parents=True, exist_ok=True)
    script_files: list[str] = []

    for filename, args in scripts_to_deploy(enabled_scripts, script_catalog):
        source = (JS_SOURCE_DIR / filename).read_text()
        (ext_js_dir / filename).write_text(wrap_iife(source, args))
        script_files.append(f"js/{filename}")

    return script_files


def _deploy_custom_script(ext_js_dir: Path) -> str:
    ext_js_dir.mkdir(parents=True, exist_ok=True)
    custom_name = "custom.js"

    if not CUSTOM_SCRIPT_PATH.is_file():
        CUSTOM_SCRIPT_PATH.write_text(DEFAULT_CUSTOM_JS)

    ext_custom = ext_js_dir / custom_name
    if ext_custom.exists() or ext_custom.is_symlink():
        ext_custom.unlink()

    shutil.copy2(CUSTOM_SCRIPT_PATH, ext_custom)

    return f"js/{custom_name}"


def _pack_extension_crx(chrome_real: str = CHROME_REAL_LINUX) -> None:
    if not os.path.isfile(chrome_real):
        raise RuntimeError(
            f"Real Chrome binary not found at {chrome_real}. "
            "Cannot pack the extension CRX (backup should have happened earlier)."
        )

    if EXTENSION_CRX_PATH.is_file():
        EXTENSION_CRX_PATH.unlink()

    cmd = [
        chrome_real,
        f"--pack-extension={EXTENSION_DIR}",
        f"--pack-extension-key={EXTENSION_KEY_PATH}",
        "--headless=new",
    ]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.append("--no-sandbox")

    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)

    packed = Path(f"{EXTENSION_DIR}.crx")
    if not packed.is_file():
        raise RuntimeError(f"Expected packed CRX at {packed}")

    if packed != EXTENSION_CRX_PATH:
        shutil.move(packed, EXTENSION_CRX_PATH)
    os.chmod(EXTENSION_CRX_PATH, 0o644)


def register_system_extension(version: str = "1.0") -> str:
    if IS_WINDOWS:
        return extension_id()

    ext_id = extension_id()
    _pack_extension_crx()

    EXTENSION_UPDATES_XML.write_text(f"""<?xml version='1.0' encoding='UTF-8'?>
<gupdate xmlns='http://www.google.com/update2/response' protocol='version=1'>
  <app appid='{ext_id}'>
    <updatecheck codebase='file://{EXTENSION_CRX_PATH}' version='{version}' />
  </app>
</gupdate>
""")
    os.chmod(EXTENSION_UPDATES_XML, 0o644)

    LINUX_CHROME_POLICY_DIR.mkdir(parents=True, exist_ok=True)
    policy = {
        "ExtensionSettings": {
            ext_id: {
                "installation_mode": "force_installed",
                "update_url": f"file://{EXTENSION_UPDATES_XML}",
            }
        }
    }
    LINUX_CHROME_POLICY_FILE.write_text(json.dumps(policy, indent=2) + "\n")
    os.chmod(LINUX_CHROME_POLICY_FILE, 0o644)

    for ext_dir in LINUX_CHROME_EXTERNAL_DIRS:
        ext_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(ext_dir, 0o755)
        external_json = ext_dir / f"{ext_id}.json"
        external_json.write_text(
            json.dumps(
                {
                    "external_crx": str(EXTENSION_CRX_PATH),
                    "external_version": version,
                },
                indent=2,
            )
            + "\n"
        )
        os.chmod(external_json, 0o644)

    return ext_id


def unregister_system_extension() -> None:
    if IS_WINDOWS:
        return

    ext_id = None
    if EXTENSION_KEY_PATH.is_file():
        try:
            ext_id = extension_id()
        except subprocess.CalledProcessError, OSError:
            ext_id = None

    for path in (
        LINUX_CHROME_POLICY_FILE,
        EXTENSION_UPDATES_XML,
        EXTENSION_CRX_PATH,
    ):
        if path.is_file():
            path.unlink()

    if ext_id:
        for ext_dir in LINUX_CHROME_EXTERNAL_DIRS:
            external_json = ext_dir / f"{ext_id}.json"
            if external_json.is_file():
                external_json.unlink()


def setup(
    enabled_scripts: list[str],
    script_catalog: dict[str, tuple[str, list | None]],
    *,
    chrome_real: str = CHROME_REAL_LINUX,
) -> Path:
    UNTRACE_ROOT.mkdir(parents=True, exist_ok=True)

    if EXTENSION_DIR.exists():
        shutil.rmtree(EXTENSION_DIR)
    EXTENSION_DIR.mkdir(parents=True)

    public_key_b64 = _public_key_base64()

    ext_js_dir = EXTENSION_DIR / "js"
    script_files = _deploy_stealth_scripts(ext_js_dir, enabled_scripts, script_catalog)
    script_files.append(_deploy_custom_script(ext_js_dir))

    version = _extension_version()
    manifest = build_manifest(script_files, public_key_b64, version)
    (EXTENSION_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    os.chmod(EXTENSION_DIR, 0o755)
    for path in EXTENSION_DIR.rglob("*"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)

    _deploy_seed_script()

    if not IS_WINDOWS and os.geteuid() == 0:
        register_system_extension(version)

    return CUSTOM_SCRIPT_PATH


def remove() -> None:
    unregister_system_extension()
    if EXTENSION_DIR.is_dir():
        shutil.rmtree(EXTENSION_DIR)
    if SEED_PROFILE_SCRIPT.is_file():
        SEED_PROFILE_SCRIPT.unlink()


def _deploy_seed_script() -> None:
    script = f'''#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

UNTRACE_ROOT = Path(__file__).resolve().parent
EXTENSION_DIR = UNTRACE_ROOT / "extension"
LOCATION_UNPACKED = 4


def extension_id_from_public_key(public_key_b64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(public_key_b64)).digest()
    return "".join(
        chr(ord("a") + (digest[i] >> 4)) + chr(ord("a") + (digest[i] & 0x0F))
        for i in range(16)
    )


def extension_settings_entry(ext_id: str, manifest: dict, dest: Path) -> dict:
    install_time = str(int(time.time() * 1_000_000))
    return {{
        "location": LOCATION_UNPACKED,
        "path": str(dest),
        "state": 1,
        "manifest": manifest,
        "was_installed_by_default": False,
        "was_installed_by_oem": False,
        "first_install_time": install_time,
    }}


def seed(profile_dir: str) -> None:
    profile = Path(profile_dir)
    manifest_path = EXTENSION_DIR / "manifest.json"
    if not manifest_path.is_file():
        return

    manifest = json.loads(manifest_path.read_text())
    ext_id = extension_id_from_public_key(manifest["key"])
    ver = manifest["version"]
    dest = profile / "Default" / "Extensions" / ext_id / ver
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(EXTENSION_DIR, dest)

    prefs_path = profile / "Default" / "Preferences"
    prefs: dict = {{}}
    if prefs_path.is_file():
        try:
            prefs = json.loads(prefs_path.read_text())
        except Exception:
            prefs = {{}}

    extensions = prefs.setdefault("extensions", {{}})
    extensions.setdefault("ui", {{}})["developer_mode"] = True
    extensions.setdefault("settings", {{}})[ext_id] = extension_settings_entry(
        ext_id, manifest, dest
    )
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(2)
    try:
        seed(sys.argv[1])
    except Exception as exc:
        print(f"[untrace] seed_profile failed: {{exc}}", file=sys.stderr)
        sys.exit(1)
'''
    SEED_PROFILE_SCRIPT.write_text(script)
    SEED_PROFILE_SCRIPT.chmod(0o755)


def seed_extension_into_profile(profile_dir: Path | str) -> None:
    if IS_WINDOWS:
        return

    if not is_installed():
        return

    script = SEED_PROFILE_SCRIPT
    if not script.is_file():
        _deploy_seed_script()

    try:
        subprocess.run(
            [sys.executable, str(script), str(profile_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[untrace] seed failed for {profile_dir}: {e.stderr or e}", file=sys.stderr)
