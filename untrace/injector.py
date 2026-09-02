from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from undetected.inject import JS_DIR as JS_SOURCE_DIR
from untrace.paths import (
    IS_WINDOWS,
    LINUX_USER_UNTRACE_REL,
    SYSTEM_UNTRACE_LINUX,
    assets_dir,
    home_dirs_to_search,
    user_untrace_root,
)
from untrace.version import __version__

if IS_WINDOWS:
    SYSTEM_UNTRACE_ROOT = (
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Untrace"
    )
else:
    SYSTEM_UNTRACE_ROOT = Path(SYSTEM_UNTRACE_LINUX)

USER_UNTRACE_ROOT = user_untrace_root()

_active_root: Path | None = None

UNTRACE_ROOT: Path
CUSTOM_SCRIPT_PATH: Path
EXTENSION_KEY_PATH: Path
EXTENSION_CRX_PATH: Path
EXTENSION_UPDATES_XML: Path
SEED_PROFILE_SCRIPT: Path
PATCH_DRIVER_SCRIPT: Path


def user_deploy_roots() -> list[Path]:
    if IS_WINDOWS:
        return [USER_UNTRACE_ROOT] if USER_UNTRACE_ROOT.parts else []
    return [home / LINUX_USER_UNTRACE_REL for home in home_dirs_to_search()]


def get_untrace_root() -> Path:
    if _active_root is not None:
        return _active_root
    if custom := os.environ.get("UNTRACE_ROOT"):
        return Path(custom).expanduser()
    for root in user_deploy_roots():
        if (root / "seed_profile.py").is_file():
            return root
    return SYSTEM_UNTRACE_ROOT


def _sync_path_attrs() -> None:
    global UNTRACE_ROOT, CUSTOM_SCRIPT_PATH, EXTENSION_DIR, EXTENSION_KEY_PATH
    global EXTENSION_CRX_PATH, EXTENSION_UPDATES_XML, SEED_PROFILE_SCRIPT
    global PATCH_DRIVER_SCRIPT

    root = get_untrace_root()
    UNTRACE_ROOT = root
    CUSTOM_SCRIPT_PATH = root / "custom.js"
    EXTENSION_DIR = root / "extension"
    EXTENSION_KEY_PATH = root / "extension.pem"
    EXTENSION_CRX_PATH = root / "extension.crx"
    EXTENSION_UPDATES_XML = root / "updates.xml"
    SEED_PROFILE_SCRIPT = root / "seed_profile.py"
    PATCH_DRIVER_SCRIPT = root / "patch_driver.py"


def use_untrace_root(root: Path | str) -> Path:
    global _active_root
    _active_root = Path(root).expanduser()
    _sync_path_attrs()
    return _active_root


def use_system_root() -> Path:
    return use_untrace_root(SYSTEM_UNTRACE_ROOT)


def clear_untrace_root_override() -> None:
    global _active_root
    _active_root = None
    _sync_path_attrs()


_sync_path_attrs()

ASSETS_DIR = assets_dir()
UTILS_FILENAME = "utils.js"
CUSTOM_JS_SOURCE_DIR = Path(__file__).parent / "js"
EXTENSION_ICON_SIZES = ("16", "48", "128")

LINUX_CHROME_POLICY_DIR = Path("/etc/opt/chrome/policies/managed")
LINUX_CHROME_POLICY_FILE = LINUX_CHROME_POLICY_DIR / "untrace.json"

LINUX_CHROME_EXTERNAL_DIRS: list[Path] = [
    Path("/opt/google/chrome/extensions"),
    Path("/usr/share/google-chrome/extensions"),
]

LOCATION_UNPACKED = 4

WEBSTORE_EXTENSION_ID = "gkbambinkmelhnjlicphgbodfafhcbdi"
WEBSTORE_UPDATE_URL = "https://clients2.google.com/service/update2/crx"
# Legacy local force-install host — cleared on register/unregister.
_WINDOWS_LEGACY_LOCAL_SOURCE = "http://127.0.0.1:19264"
_WINDOWS_FORCE_LIST_KEY = r"SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist"
_WINDOWS_INSTALL_SOURCES_KEY = (
    r"SOFTWARE\Policies\Google\Chrome\ExtensionInstallSources"
)
_WINDOWS_EXTERNAL_EXTENSIONS_KEY = r"SOFTWARE\Wow6432Node\Google\Chrome\Extensions"
_WINDOWS_CRX_DOWNLOAD_URL = (
    "https://clients2.google.com/service/update2/crx"
    "?response=redirect&prodversion=9999.0.0.0&acceptformat=crx3"
    f"&x=id%3D{WEBSTORE_EXTENSION_ID}%26installsource%3Dondemand%26uc"
)
# Consumer Chrome only accepts Web Store update URLs ([BLOCKED] otherwise).
_WINDOWS_FORCE_VALUE = f"{WEBSTORE_EXTENSION_ID};{WEBSTORE_UPDATE_URL}"

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


def _windows_webstore_root() -> Path:
    return SYSTEM_UNTRACE_ROOT


def _windows_webstore_crx_path() -> Path:
    return _windows_webstore_root() / "untrace-injector.crx"


def _windows_unpacked_extension_dir() -> Path:
    return _windows_webstore_root() / "untrace-injector"


def _windows_webstore_updates_path() -> Path:
    return _windows_webstore_root() / "updates.xml"


def _crx_version(crx_bytes: bytes) -> str:
    idx = crx_bytes.find(b"PK\x03\x04")
    if idx < 0:
        return "1.0.0"
    with zipfile.ZipFile(io.BytesIO(crx_bytes[idx:])) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    version = manifest.get("version", "1.0.0")
    return str(version)


def _download_webstore_crx() -> tuple[bytes, str]:
    request = urllib.request.Request(
        _WINDOWS_CRX_DOWNLOAD_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status = getattr(response, "status", None)
            data = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Failed to download Untrace Injector from the Chrome Web Store: {exc}"
        ) from exc
    if len(data) < 16 or not data.startswith(b"Cr24"):
        raise RuntimeError(
            "Chrome Web Store is not serving a CRX for Untrace Injector "
            f"({WEBSTORE_EXTENSION_ID})"
            + (f" [HTTP {status}]" if status is not None else "")
            + ". Publish or restore the public listing, then retry install."
        )
    return data, _crx_version(data)


def _unpack_crx(crx_bytes: bytes, dest: Path) -> None:
    idx = crx_bytes.find(b"PK\x03\x04")
    if idx < 0:
        raise RuntimeError(
            "CRX payload is missing (not a valid Chrome extension archive)."
        )
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(crx_bytes[idx:])) as archive:
        archive.extractall(dest)
    if not (dest / "manifest.json").is_file():
        raise RuntimeError(f"Unpacked extension is missing manifest.json at {dest}")


def _windows_reg_list_entries(key_path: str) -> dict[str, str]:
    import winreg

    entries: dict[str, str] = {}
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ
        ) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                if isinstance(value, str):
                    entries[str(name)] = value
                i += 1
    except (FileNotFoundError, OSError):
        pass
    return entries


def _windows_force_list_entries() -> dict[str, str]:
    return _windows_reg_list_entries(_WINDOWS_FORCE_LIST_KEY)


def _set_windows_reg_list_value(key_path: str, match_prefix: str, value: str) -> None:
    import winreg

    entries = _windows_reg_list_entries(key_path)
    existing_name = next(
        (
            name
            for name, existing in entries.items()
            if existing.startswith(match_prefix)
        ),
        None,
    )
    if existing_name is None:
        used: set[int] = set()
        for name in entries:
            try:
                used.add(int(name))
            except ValueError:
                pass
        index = 1
        while index in used:
            index += 1
        existing_name = str(index)

    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, existing_name, 0, winreg.REG_SZ, value)


def _clear_windows_reg_list_prefix(key_path: str, match_prefix: str) -> None:
    import winreg

    entries = _windows_reg_list_entries(key_path)
    to_delete = [
        name for name, value in entries.items() if value.startswith(match_prefix)
    ]
    if not to_delete:
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            for name in to_delete:
                winreg.DeleteValue(key, name)
    except (FileNotFoundError, OSError):
        pass


def _windows_external_extension_key() -> str:
    return f"{_WINDOWS_EXTERNAL_EXTENSIONS_KEY}\\{WEBSTORE_EXTENSION_ID}"


def _set_windows_external_extension_update_url() -> None:
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE,
        _windows_external_extension_key(),
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "update_url", 0, winreg.REG_SZ, WEBSTORE_UPDATE_URL)


def _clear_windows_external_extension() -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, _windows_external_extension_key())
    except (FileNotFoundError, OSError):
        pass


def is_windows_webstore_extension_registered() -> bool:
    if not IS_WINDOWS:
        return False
    force = _windows_force_list_entries()
    return any(
        value == _WINDOWS_FORCE_VALUE
        or (
            value.startswith(f"{WEBSTORE_EXTENSION_ID};")
            and WEBSTORE_UPDATE_URL in value
        )
        for value in force.values()
    )


def register_windows_webstore_extension() -> str:
    if not IS_WINDOWS:
        raise RuntimeError("Web Store extension install is Windows-only")

    crx_path = _windows_webstore_crx_path()
    try:
        crx_bytes, _version = _download_webstore_crx()
    except RuntimeError:
        if not crx_path.is_file():
            raise
        crx_bytes = crx_path.read_bytes()

    root = _windows_webstore_root()
    root.mkdir(parents=True, exist_ok=True)
    from untrace import config

    prior = _active_root
    try:
        use_untrace_root(root)
        cfg = config.load()
        cfg["js_injection"] = True
        config.save(cfg)
    finally:
        if prior is not None:
            use_untrace_root(prior)
        else:
            clear_untrace_root_override()

    crx_path.write_bytes(crx_bytes)
    _unpack_crx(crx_bytes, _windows_unpacked_extension_dir())
    _set_windows_reg_list_value(
        _WINDOWS_FORCE_LIST_KEY, f"{WEBSTORE_EXTENSION_ID};", _WINDOWS_FORCE_VALUE
    )
    _clear_windows_reg_list_prefix(
        _WINDOWS_INSTALL_SOURCES_KEY, _WINDOWS_LEGACY_LOCAL_SOURCE
    )
    _set_windows_external_extension_update_url()
    return WEBSTORE_EXTENSION_ID


def unregister_windows_webstore_extension() -> None:
    if not IS_WINDOWS:
        return

    _clear_windows_reg_list_prefix(_WINDOWS_FORCE_LIST_KEY, f"{WEBSTORE_EXTENSION_ID};")
    _clear_windows_reg_list_prefix(
        _WINDOWS_INSTALL_SOURCES_KEY, _WINDOWS_LEGACY_LOCAL_SOURCE
    )
    _clear_windows_external_extension()
    unpacked = _windows_unpacked_extension_dir()
    if unpacked.is_dir():
        shutil.rmtree(unpacked)
    for path in (
        _windows_webstore_crx_path(),
        _windows_webstore_updates_path(),
        _windows_webstore_root() / "seed_profile.py",
    ):
        if path.is_file():
            path.unlink()


def extension_id_from_public_key(public_key_b64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(public_key_b64)).digest()
    return "".join(
        chr(ord("a") + (digest[i] >> 4)) + chr(ord("a") + (digest[i] & 0x0F))
        for i in range(16)
    )


def _extension_private_key_valid() -> bool:
    if not EXTENSION_KEY_PATH.is_file():
        return False
    try:
        subprocess.run(
            [
                "openssl",
                "rsa",
                "-in",
                str(EXTENSION_KEY_PATH),
                "-check",
                "-noout",
            ],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _ensure_extension_private_key() -> None:
    if _extension_private_key_valid():
        return
    if EXTENSION_KEY_PATH.is_file():
        EXTENSION_KEY_PATH.unlink()
    subprocess.run(
        ["openssl", "genrsa", "-out", str(EXTENSION_KEY_PATH), "2048"],
        check=True,
    )
    EXTENSION_KEY_PATH.chmod(0o600)


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
    return __version__


def wrap_iife(source: str, args: list | None = None) -> str:
    source = source.strip()
    if args is not None:
        args_literal = ", ".join(json.dumps(a) for a in args)
        return f"({source})({args_literal});\n"
    return f"({source})();\n"


def extension_icon_paths() -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for size in EXTENSION_ICON_SIZES:
        path = ASSETS_DIR / f"icon-{size}.png"
        if not path.is_file():
            fallback = ASSETS_DIR / "icon.png"
            if size == "128" and fallback.is_file():
                path = fallback
            else:
                raise FileNotFoundError(f"Missing extension icon: {path}")
        paths[size] = path
    return paths


def _deploy_extension_icons(ext_root: Path) -> dict[str, str]:
    icons_dir = ext_root / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    icons: dict[str, str] = {}
    for size, src in extension_icon_paths().items():
        name = f"icon-{size}.png"
        shutil.copy2(src, icons_dir / name)
        icons[size] = f"icons/{name}"
    return icons


def build_manifest(
    script_files: list[str],
    public_key_b64: str | None = None,
    version: str = "1.0",
    *,
    icons: dict[str, str] | None = None,
) -> dict:
    manifest: dict = {
        "manifest_version": 3,
        "name": "untrace",
        "version": version,
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
    if public_key_b64:
        manifest["key"] = public_key_b64
    if icons:
        manifest["icons"] = icons
        manifest["action"] = {"default_icon": icons}
    return manifest


def build_store_manifest(
    script_files: list[str],
    version: str = "1.0",
    *,
    icons: dict[str, str] | None = None,
) -> dict:
    return build_manifest(script_files, None, version, icons=icons)


def pack_extension_zip(
    output: Path,
    enabled_scripts: list[str],
    script_catalog: dict[str, tuple[str, list | None]],
    *,
    version: str | None = None,
) -> Path:
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ver = version or _extension_version()

    with tempfile.TemporaryDirectory(prefix="untrace-ext-") as tmp:
        root = Path(tmp) / "extension"
        js_dir = root / "js"
        script_files = _deploy_stealth_scripts(js_dir, enabled_scripts, script_catalog)
        custom_name = "custom.js"
        custom_src = CUSTOM_JS_SOURCE_DIR / custom_name
        if custom_src.is_file():
            shutil.copy2(custom_src, js_dir / custom_name)
        else:
            (js_dir / custom_name).write_text(DEFAULT_CUSTOM_JS)
        script_files.append(f"js/{custom_name}")

        icons = _deploy_extension_icons(root)
        manifest = build_store_manifest(script_files, ver, icons=icons)
        (root / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

        if output.is_file():
            output.unlink()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(root).as_posix())

    return output


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


def unregister_system_extension() -> None:
    if IS_WINDOWS:
        unregister_windows_webstore_extension()
        return

    ext_id = None
    if EXTENSION_KEY_PATH.is_file():
        try:
            ext_id = extension_id()
        except (subprocess.CalledProcessError, OSError):
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
) -> Path:
    UNTRACE_ROOT.mkdir(parents=True, exist_ok=True)

    if EXTENSION_DIR.exists():
        shutil.rmtree(EXTENSION_DIR)
    EXTENSION_DIR.mkdir(parents=True)

    public_key_b64 = _public_key_base64()

    ext_js_dir = EXTENSION_DIR / "js"
    script_files = _deploy_stealth_scripts(ext_js_dir, enabled_scripts, script_catalog)
    script_files.append(_deploy_custom_script(ext_js_dir))
    icons = _deploy_extension_icons(EXTENSION_DIR)

    version = _extension_version()
    manifest = build_manifest(script_files, public_key_b64, version, icons=icons)
    (EXTENSION_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    EXTENSION_DIR.chmod(0o755)
    for path in EXTENSION_DIR.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)

    _deploy_seed_script()
    _deploy_patch_driver_script()

    if not IS_WINDOWS and os.geteuid() == 0:
        unregister_system_extension()

    return CUSTOM_SCRIPT_PATH


def remove() -> None:
    unregister_system_extension()
    if EXTENSION_DIR.is_dir():
        shutil.rmtree(EXTENSION_DIR)
    if SEED_PROFILE_SCRIPT.is_file():
        SEED_PROFILE_SCRIPT.unlink()
    if PATCH_DRIVER_SCRIPT.is_file():
        PATCH_DRIVER_SCRIPT.unlink()


def user_deploy_has_payload(root: Path) -> bool:
    if not root.is_dir():
        return False
    for path in root.iterdir():
        if path.name == "untrace.log":
            continue
        return True
    return False


def remove_user_deploys() -> list[Path]:
    removed: list[Path] = []
    for root in user_deploy_roots():
        if not root.is_dir():
            continue
        shutil.rmtree(root, ignore_errors=True)
        if not root.exists():
            removed.append(root)
    return removed


def _patch_driver_script_source() -> str:
    from undetected.cdc import (
        CDC_INJECTION_RE,
        ENABLE_AUTOMATION,
        TEST_TYPE_WEBDRIVER,
    )

    marker = "untrace chromedriver"
    return f'''#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

MARKER = b"{marker}"
CDC_INJECTION_RE = re.compile({CDC_INJECTION_RE.pattern!r})

STRING_PATCHES = [({TEST_TYPE_WEBDRIVER!r}, b" " * {len(TEST_TYPE_WEBDRIVER)})]
if sys.platform != "win32":
    STRING_PATCHES.append(({ENABLE_AUTOMATION!r}, b" " * {len(ENABLE_AUTOMATION)}))


def patch_driver(path: str) -> bool:
    target = Path(path)
    try:
        content = target.read_bytes()
    except OSError:
        return False
    if MARKER in content:
        return True
    if not CDC_INJECTION_RE.search(content):
        return False

    config_path = Path(__file__).resolve().parent / "config.json"
    try:
        cfg = json.loads(config_path.read_text())
    except Exception:
        cfg = {{}}
    if not cfg.get("chromedriver_patch", True):
        return True

    backup = Path(str(target) + ".untrace.bak")
    if not backup.is_file():
        shutil.copy2(target, backup)
        backup.chmod(0o755)

    replacement = b'{{console.log("{marker}")}}'
    updated = CDC_INJECTION_RE.sub(
        lambda match: replacement.ljust(len(match.group(0)), b" "),
        content,
        count=1,
    )
    for old, new in STRING_PATCHES:
        updated = updated.replace(old, new)
    target.write_bytes(updated)
    target.chmod(0o755)
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(2)
    sys.exit(0 if patch_driver(sys.argv[1]) else 1)
'''


PATCH_DRIVER_SCRIPT_SOURCE = _patch_driver_script_source()


def _deploy_patch_driver_script() -> None:
    PATCH_DRIVER_SCRIPT.write_text(PATCH_DRIVER_SCRIPT_SOURCE)
    PATCH_DRIVER_SCRIPT.chmod(0o755)


def _deploy_seed_script() -> None:
    script = """#!/usr/bin/env python3
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


def extension_id_from_path(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode()).digest()
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


def _load_prefs(profile: Path) -> dict:
    prefs_path = profile / "Default" / "Preferences"
    if not prefs_path.is_file():
        return {}
    try:
        return json.loads(prefs_path.read_text())
    except Exception:
        return {}


def _write_prefs(profile: Path, prefs: dict) -> None:
    prefs_path = profile / "Default" / "Preferences"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs, indent=2))


def install_unpacked(profile: Path, prefs: dict, src: Path) -> bool:
    src = src.resolve()
    manifest_path = src / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception:
        return False

    if "key" in manifest:
        ext_id = extension_id_from_public_key(manifest["key"])
    else:
        ext_id = extension_id_from_path(src)

    ver = str(manifest.get("version", "0.0.0.0"))
    dest = profile / "Default" / "Extensions" / ext_id / ver
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)

    extensions = prefs.setdefault("extensions", {})
    extensions.setdefault("ui", {})["developer_mode"] = True
    extensions.setdefault("settings", {})[ext_id] = extension_settings_entry(
        ext_id, manifest, dest
    )
    return True


def seed(profile_dir: str, *extra_extension_dirs: str) -> bool:
    profile = Path(profile_dir)
    prefs = _load_prefs(profile)
    changed = False

    config_path = UNTRACE_ROOT / "config.json"
    cfg: dict = {}
    if config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text())
        except Exception:
            cfg = {}

    extension_required = bool(cfg.get("js_injection", True))
    extension_installed = False
    if extension_required:
        extension_installed = install_unpacked(profile, prefs, EXTENSION_DIR)
        changed = changed or extension_installed

    for extra in extra_extension_dirs:
        src = Path(extra)
        if src.is_dir() and install_unpacked(profile, prefs, src):
            changed = True

    if changed:
        _write_prefs(profile, prefs)
    return extension_installed or not extension_required


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(2)
    try:
        seeded = seed(sys.argv[1], *sys.argv[2:])
    except Exception as exc:
        print(f"[untrace] seed_profile failed: {exc}", file=sys.stderr)
        sys.exit(1)
    if not seeded:
        print(
            "[untrace] seed_profile: stealth extension not installed",
            file=sys.stderr,
        )
        sys.exit(1)
"""
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
        print(
            f"[untrace] seed failed for {profile_dir}: {e.stderr or e}", file=sys.stderr
        )
