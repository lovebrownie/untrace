from __future__ import annotations

import base64
import datetime
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

if not IS_WINDOWS:
    import pwd
else:
    pwd = None  # type: ignore[assignment]

if IS_WINDOWS:
    SYSTEM_UNTRACE_ROOT = (
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Untrace"
    )
    USER_UNTRACE_ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "Untrace"
else:
    SYSTEM_UNTRACE_ROOT = Path("/etc/untrace")
    USER_UNTRACE_ROOT = Path.home() / ".local" / "share" / "untrace"

_active_root: Path | None = None

UNTRACE_ROOT: Path
USER_CHROME_WRAPPER: Path
CUSTOM_SCRIPT_PATH: Path
EXTENSION_KEY_PATH: Path
EXTENSION_CRX_PATH: Path
EXTENSION_UPDATES_XML: Path
SEED_PROFILE_SCRIPT: Path


def user_deploy_roots() -> list[Path]:
    if IS_WINDOWS:
        return [USER_UNTRACE_ROOT] if USER_UNTRACE_ROOT else []

    homes: list[Path] = []
    seen: set[Path] = set()

    def add_home(home: Path) -> None:
        resolved = home.expanduser().resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        homes.append(resolved)

    add_home(Path.home())
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and pwd is not None:
        try:
            add_home(Path(pwd.getpwnam(sudo_user).pw_dir))
        except KeyError:
            add_home(Path(f"/home/{sudo_user}"))

    return [home / ".local" / "share" / "untrace" for home in homes]


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
    global USER_CHROME_WRAPPER

    root = get_untrace_root()
    UNTRACE_ROOT = root
    USER_CHROME_WRAPPER = USER_UNTRACE_ROOT / "chrome"
    CUSTOM_SCRIPT_PATH = root / "custom.js"
    EXTENSION_DIR = root / "extension"
    EXTENSION_KEY_PATH = root / "extension.pem"
    EXTENSION_CRX_PATH = root / "extension.crx"
    EXTENSION_UPDATES_XML = root / "updates.xml"
    SEED_PROFILE_SCRIPT = root / "seed_profile.py"


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

WEBSTORE_EXTENSION_ID = "mgnlenokophofdnmlabkgpmlnolgomgj"
WEBSTORE_UPDATE_URL = "https://clients2.google.com/service/update2/crx"
WEBSTORE_EXTENSION_URL = (
    f"https://chromewebstore.google.com/detail/untrace-injector/{WEBSTORE_EXTENSION_ID}"
)
WEBSTORE_HTTP_PORT = 19264
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
_WINDOWS_LOCAL_UPDATE_URL = f"http://127.0.0.1:{WEBSTORE_HTTP_PORT}/updates.xml"
_WINDOWS_LOCAL_CRX_URL = f"http://127.0.0.1:{WEBSTORE_HTTP_PORT}/untrace-injector.crx"
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


def is_policy_registered() -> bool:
    if IS_WINDOWS:
        return is_windows_webstore_extension_registered()
    return LINUX_CHROME_POLICY_FILE.is_file()


def is_fully_registered() -> bool:
    if IS_WINDOWS:
        return is_windows_webstore_extension_registered()
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
            data = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Failed to download Untrace Injector from the Chrome Web Store: {exc}"
        ) from exc
    if len(data) < 16 or not data.startswith(b"Cr24"):
        raise RuntimeError(
            "Chrome Web Store download did not return a CRX (check network / extension id)."
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


def _write_windows_local_updates_xml(version: str) -> Path:
    path = _windows_webstore_updates_path()
    path.write_text(
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>\n"
        f"  <app appid='{WEBSTORE_EXTENSION_ID}'>\n"
        f"    <updatecheck codebase='{_WINDOWS_LOCAL_CRX_URL}' version='{version}' />\n"
        "  </app>\n"
        "</gupdate>\n",
        encoding="utf-8",
    )
    return path


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
    except FileNotFoundError, OSError:
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
    except FileNotFoundError, OSError:
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
    except FileNotFoundError, OSError:
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


def _windows_seed_script_path() -> Path:
    return _windows_webstore_root() / "seed_profile.py"


def _write_windows_seed_script() -> Path:
    script = f'''#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

UNTRACE_ROOT = Path(__file__).resolve().parent
EXTENSION_DIR = UNTRACE_ROOT / "untrace-injector"
EXT_ID = "{WEBSTORE_EXTENSION_ID}"
LOCATION_UNPACKED = 4


def seed(profile_dir: str) -> None:
    config_path = UNTRACE_ROOT / "config.json"
    if config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {{}}
        if not cfg.get("js_injection", True):
            return

    manifest_path = EXTENSION_DIR / "manifest.json"
    if not manifest_path.is_file():
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ver = str(manifest.get("version", "0"))
    profile = Path(profile_dir)
    dest = profile / "Default" / "Extensions" / EXT_ID / ver
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(EXTENSION_DIR, dest)

    prefs_path = profile / "Default" / "Preferences"
    prefs: dict = {{}}
    if prefs_path.is_file():
        try:
            prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        except Exception:
            prefs = {{}}

    install_time = str(int(time.time() * 1_000_000))
    extensions = prefs.setdefault("extensions", {{}})
    extensions.setdefault("ui", {{}})["developer_mode"] = True
    extensions.setdefault("settings", {{}})[EXT_ID] = {{
        "location": LOCATION_UNPACKED,
        "path": str(dest),
        "state": 1,
        "manifest": manifest,
        "was_installed_by_default": False,
        "was_installed_by_oem": False,
        "first_install_time": install_time,
    }}
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(2)
    try:
        seed(sys.argv[1])
    except Exception as exc:
        print(f"[untrace] seed_profile failed: {{exc}}", file=sys.stderr)
        sys.exit(1)
'''
    path = _windows_seed_script_path()
    path.write_text(script, encoding="utf-8")
    return path


def register_windows_webstore_extension() -> str:
    if not IS_WINDOWS:
        raise RuntimeError("Web Store extension install is Windows-only")

    crx_path = _windows_webstore_crx_path()
    try:
        crx_bytes, version = _download_webstore_crx()
    except RuntimeError:
        if not crx_path.is_file():
            raise
        crx_bytes = crx_path.read_bytes()
        version = _crx_version(crx_bytes)

    root = _windows_webstore_root()
    root.mkdir(parents=True, exist_ok=True)
    cfg_path = root / "config.json"
    cfg: dict = {}
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError, OSError:
            cfg = {}
    cfg["js_injection"] = True
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    crx_path.write_bytes(crx_bytes)
    _unpack_crx(crx_bytes, _windows_unpacked_extension_dir())
    _write_windows_local_updates_xml(version)
    _write_windows_seed_script()
    _set_windows_reg_list_value(
        _WINDOWS_FORCE_LIST_KEY, f"{WEBSTORE_EXTENSION_ID};", _WINDOWS_FORCE_VALUE
    )
    _clear_windows_reg_list_prefix(
        _WINDOWS_INSTALL_SOURCES_KEY, f"http://127.0.0.1:{WEBSTORE_HTTP_PORT}"
    )
    _set_windows_external_extension_update_url()
    return WEBSTORE_EXTENSION_ID


def unregister_windows_webstore_extension() -> None:
    if not IS_WINDOWS:
        return

    _clear_windows_reg_list_prefix(_WINDOWS_FORCE_LIST_KEY, f"{WEBSTORE_EXTENSION_ID};")
    _clear_windows_reg_list_prefix(
        _WINDOWS_INSTALL_SOURCES_KEY, f"http://127.0.0.1:{WEBSTORE_HTTP_PORT}"
    )
    _clear_windows_external_extension()
    unpacked = _windows_unpacked_extension_dir()
    if unpacked.is_dir():
        shutil.rmtree(unpacked)
    for path in (
        _windows_webstore_crx_path(),
        _windows_webstore_updates_path(),
        _windows_seed_script_path(),
    ):
        if path.is_file():
            path.unlink()


def extension_launch_flags() -> list[str]:
    return []


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
    return f"1.{(ts // (65536 * 65536)) % 65536}.{(ts // 65536) % 65536}.{ts % 65536}"


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


def build_store_manifest(script_files: list[str], version: str = "1.0") -> dict:
    manifest = build_manifest(script_files, "", version)
    del manifest["key"]
    return manifest


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
        script_files = _deploy_stealth_scripts(
            js_dir, enabled_scripts, script_catalog
        )
        custom_name = "custom.js"
        custom_src = JS_SOURCE_DIR / custom_name
        if custom_src.is_file():
            shutil.copy2(custom_src, js_dir / custom_name)
        else:
            (js_dir / custom_name).write_text(DEFAULT_CUSTOM_JS)
        script_files.append(f"js/{custom_name}")

        manifest = build_store_manifest(script_files, ver)
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
        return register_windows_webstore_extension()

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
        unregister_windows_webstore_extension()
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
        unregister_system_extension()

    return CUSTOM_SCRIPT_PATH


def remove() -> None:
    unregister_system_extension()
    if EXTENSION_DIR.is_dir():
        shutil.rmtree(EXTENSION_DIR)
    if SEED_PROFILE_SCRIPT.is_file():
        SEED_PROFILE_SCRIPT.unlink()


def remove_user_deploys() -> list[Path]:
    removed: list[Path] = []
    for root in user_deploy_roots():
        if not root.is_dir():
            continue
        shutil.rmtree(root)
        removed.append(root)
    return removed


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


def seed(profile_dir: str) -> None:
    profile = Path(profile_dir)
    config_path = UNTRACE_ROOT / "config.json"
    if config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text())
        except Exception:
            cfg = {}
        if not cfg.get("js_injection", True):
            return

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
    prefs: dict = {}
    if prefs_path.is_file():
        try:
            prefs = json.loads(prefs_path.read_text())
        except Exception:
            prefs = {}

    extensions = prefs.setdefault("extensions", {})
    extensions.setdefault("ui", {})["developer_mode"] = True
    extensions.setdefault("settings", {})[ext_id] = extension_settings_entry(
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
        print(f"[untrace] seed_profile failed: {exc}", file=sys.stderr)
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
