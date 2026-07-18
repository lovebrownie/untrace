#!/usr/bin/env python3
import argparse
import glob
import json
import os
import platform
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from untrace import chromedriver_patch, config, injector, selenium_manager_patch

IS_WINDOWS = platform.system() == "Windows"

if not IS_WINDOWS:
    import pwd
else:
    pwd = None  # type: ignore[assignment]

CHROMEDRIVER_STRIP_FLAGS: tuple[str, ...] = (
    "--enable-automation",
    "--disable-automatio",
    "--test-type=webdriver",
    "--use-mock-keychain",
    "--allow-pre-commit-input",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-client-side-phishing-detection",
    "--disable-default-apps",
    "--disable-hang-monitor",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-sync",
    "--enable-logging=stderr",
    "--no-service-autorun",
    "--password-store=basic",
    "--disable-features=IgnoreDuplicateNavs,Prewarm",
    "--disable-blink-features=AutomationControlled",
)

LAUNCH_FLAGS_FILE = "launch.flags"

CHROME_FLAGS: dict[str, str] = {
    "start-maximized": "--start-maximized",
    "no-default-browser-check": "--no-default-browser-check",
    "no-first-run": "--no-first-run",
    "lang": "--lang=en-US",
    "accept-lang": "--accept-lang=en-US,en",
    "disable-automation-mode": (
        "--disable-features=AutomationModeDesktop,AutomationModeAndroid,"
        "AutomationControlled"
    ),
    "remote-allow-origins": "--remote-allow-origins=*",
}

CHROME_SCRIPTS: dict[str, tuple[str, list | None]] = {
    "navigator.userAgent": ("navigator.userAgent.js", None),
    "navigator.headless": ("navigator.headless.js", None),
    "cdp": ("cdp.js", None),
    "akamai": ("akamai.js", None),
    "sourceurl": ("sourceurl.js", None),
    "navigator.webdriver": ("navigator.webdriver.js", None),
    "chrome.app": ("chrome.app.js", None),
    "chrome.runtime": ("chrome.runtime.js", [False]),
    "chrome.csi": ("chrome.csi.js", None),
    "chrome.loadTimes": ("chrome.loadTimes.js", None),
    "iframe.contentWindow": ("iframe.contentWindow.js", None),
    "iframe.webdriver": ("iframe.webdriver.js", None),
    "media.codecs": ("media.codecs.js", None),
    "navigator.languages": ("navigator.languages.js", [["en-US", "en"]]),
    "navigator.permissions": ("navigator.permissions.js", None),
    "navigator.plugins": ("navigator.plugins.js", None),
    "navigator.vendor": ("navigator.vendor.js", ["Google Inc."]),
    "webgl.vendor": ("webgl.vendor.js", ["Intel Inc.", "Intel Iris OpenGL Engine"]),
    "window.outerdimensions": ("window.outerdimensions.js", None),
    "hairline.fix": ("hairline.fix.js", None),
    "cleanup": ("cleanup.js", None),
}

DEFAULT_CHROME_FLAGS: tuple[str, ...] = tuple(CHROME_FLAGS.keys())
OPTIONAL_CHROME_SCRIPTS: frozenset[str] = frozenset(
    {
        "hairline.fix",
        "navigator.permissions",
        "media.codecs",
        "navigator.plugins",
        "chrome.app",
        "chrome.runtime",
        "chrome.csi",
        "chrome.loadTimes",
        "iframe.contentWindow",
    }
)
DEFAULT_CHROME_SCRIPTS: tuple[str, ...] = tuple(
    name for name in CHROME_SCRIPTS if name not in OPTIONAL_CHROME_SCRIPTS
)


def _chrome_full_version() -> str | None:
    try:
        out = subprocess.check_output(
            [chrome_real_binary(), "--version"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=5,
        )
    except subprocess.SubprocessError, OSError:
        return None
    parts = out.strip().split()
    return parts[-1] if len(parts) >= 3 else None


def _chrome_user_agent_flag() -> str | None:
    version = _chrome_full_version()
    if not version:
        return None
    ua = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version} Safari/537.36"
    )
    return f"--user-agent={ua}"


def chrome_launch_flags() -> list[str]:
    cfg = config.load()
    flags: list[str] = []
    if cfg.get("chrome_flags", True):
        flags.extend(CHROME_FLAGS[name] for name in DEFAULT_CHROME_FLAGS)
        ua_flag = _chrome_user_agent_flag()
        if ua_flag:
            flags.append(ua_flag)
    if cfg.get("js_injection", True):
        flags.extend(injector.extension_launch_flags())
    return flags


def _chown_to_sudo_user(path: Path) -> None:
    if IS_WINDOWS or pwd is None:
        return
    sudo_user = os.environ.get("SUDO_USER")
    if not sudo_user or os.geteuid() != 0 or not path.exists():
        return
    try:
        pw = pwd.getpwnam(sudo_user)
    except KeyError:
        return
    for entry in sorted(path.rglob("*"), reverse=True):
        try:
            os.chown(entry, pw.pw_uid, pw.pw_gid)
        except OSError:
            pass
    try:
        os.chown(path, pw.pw_uid, pw.pw_gid)
    except OSError:
        pass


def write_launch_flags(flags: list[str], root: Path) -> Path:
    path = root / LAUNCH_FLAGS_FILE
    root.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(flags) + ("\n" if flags else ""))
    os.chmod(path, 0o644)
    if root in injector.user_deploy_roots():
        _chown_to_sudo_user(root)
    return path


def _sync_launch_flags(
    launch_flags: list[str], roots: list[Path] | None = None
) -> None:
    targets = roots if roots is not None else _managed_untrace_roots()
    for root in targets:
        if root == injector.SYSTEM_UNTRACE_ROOT and os.geteuid() != 0:
            continue
        root.mkdir(parents=True, exist_ok=True)
        write_launch_flags(launch_flags, root)


def format_enabled_scripts() -> str:
    return ", ".join(DEFAULT_CHROME_SCRIPTS)


def format_enabled_flags() -> str:
    return ", ".join(DEFAULT_CHROME_FLAGS)


def random_user_data_dir() -> str:
    rand_suffix = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    if IS_WINDOWS:
        base = os.path.expandvars(r"%TEMP%\chrome_random_profiles")
    else:
        base = "/tmp/chrome_random_profiles"
    path = os.path.join(base, f"profile_{rand_suffix}")
    os.makedirs(path, exist_ok=True)
    injector.seed_extension_into_profile(path)
    return path


CHROME_SCRIPT = "/opt/google/chrome/google-chrome"
CHROME_BINARY = "/opt/google/chrome/chrome"
CHROME_REAL_NAME = "chrome_real"
BACKUP_SUFFIX = ".bak"
ORIGINAL_LINE = 'exec -a "$0" "$HERE/chrome" "$@"'


def backup_path_linux():
    return CHROME_SCRIPT + BACKUP_SUFFIX


def sudo_command() -> str:
    args = sys.argv[1:]
    if sys.argv[0].endswith("__main__.py"):
        return f"sudo {sys.executable} -m untrace {' '.join(args)}"
    return f"sudo {sys.executable} {' '.join(sys.argv)}"


def require_root():
    if os.geteuid() != 0:
        print("This action needs root. Re-run with sudo:")
        print(f" {sudo_command()}")
        sys.exit(1)


def read_script_linux():
    if not os.path.isfile(CHROME_SCRIPT):
        print(
            f"Error: {CHROME_SCRIPT} not found. Is Chrome installed?", file=sys.stderr
        )
        sys.exit(1)
    with open(CHROME_SCRIPT, "r") as f:
        return f.read()


def chrome_real_path() -> str:
    return os.path.join(os.path.dirname(CHROME_BINARY), CHROME_REAL_NAME)


def is_legacy_launcher_patched_linux(content: str) -> bool:
    return "--user-data-dir" in content and "chrome_random_profiles" in content


def is_chrome_wrapped_linux() -> bool:
    return os.path.isfile(chrome_real_path())


def is_patched_linux(content: str) -> bool:
    return is_chrome_wrapped_linux()


UNTRACE_BEGIN = "# === UNTRACE BEGIN ==="
UNTRACE_END = "# === UNTRACE END ==="

AUTOMATION_DETECT_BASH = """
UNTRACE_AUTOMATION=0
for arg in "$@"; do
  case "$arg" in
    --remote-debugging-port*|--test-type=webdriver|--test-type=webbrowse|--enable-automation|--disable-automatio)
      UNTRACE_AUTOMATION=1
      break
      ;;
  esac
done
"""

HEADLESS_DETECT_BASH = """
_untrace_wants_headless=0
_untrace_headless_extras=()
for arg in "$@"; do
  case "$arg" in
    --headless|--headless=*)
      _untrace_wants_headless=1
      _untrace_headless_extras=(--window-size=1920,1080 --ozone-override-screen-size=1920,1080)
      break
      ;;
  esac
done
"""

CHROME_RUNNER_BASH = """
_untrace_runner=("$CHROME_REAL")
if [ "$_untrace_wants_headless" = "1" ] && command -v xvfb-run >/dev/null 2>&1; then
  _untrace_runner=(xvfb-run -a -s "-screen 0 1920x1080x24" "$CHROME_REAL")
fi
"""

SEED_EXTENSION_BASH = """
_resolve_untrace_root() {
  if [ -n "${UNTRACE_ROOT:-}" ] && [ -f "${UNTRACE_ROOT}/seed_profile.py" ]; then
    printf '%s\\n' "$UNTRACE_ROOT"
    return 0
  fi
  if [ -f "${HOME}/.local/share/untrace/seed_profile.py" ]; then
    printf '%s\\n' "${HOME}/.local/share/untrace"
    return 0
  fi
  printf '%s\\n' "/etc/untrace"
}

_seed_untrace_extension() {
  local pdir="$1"
  local root
  [ -n "$pdir" ] || return 0
  root="$(_resolve_untrace_root)"
  mkdir -p "$pdir"
  "$root/seed_profile.py" "$pdir" || true
}
"""

READ_LAUNCH_FLAGS_BASH = """
_untrace_launch_flags=()
_read_launch_flags() {
  local root f line
  root="$(_resolve_untrace_root)"
  f="$root/launch.flags"
  _untrace_launch_flags=()
  [ -f "$f" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -n "$line" ] || continue
    _untrace_launch_flags+=("$line")
  done < "$f"
}
"""

PARSE_USER_DATA_DIR_BASH = """
_untrace_user_data_dir=""
_untrace_prev=""
for arg in "$@"; do
  if [ "$_untrace_prev" = "--user-data-dir" ]; then
    _untrace_user_data_dir="$arg"
    _untrace_prev=""
    continue
  fi
  case "$arg" in
    --user-data-dir=*)
      _untrace_user_data_dir="${arg#--user-data-dir=}"
      ;;
    --user-data-dir)
      _untrace_prev="--user-data-dir"
      ;;
  esac
done
"""

RANDOM_DIR_BASH = """
RANDOM_DIR="$(mktemp -d /tmp/chrome_random_profiles/profile_XXXXXXXXXX 2>/dev/null || echo "/tmp/chrome_random_profiles/profile_$(date +%s%N | sha256sum | cut -c1-16)")"
mkdir -p "$RANDOM_DIR"
_seed_untrace_extension "$RANDOM_DIR"
"""


def _chromedriver_strip_case_pattern() -> str:
    arms = [
        flag
        for flag in CHROMEDRIVER_STRIP_FLAGS
        if flag != "--disable-blink-features=AutomationControlled"
    ]
    arms.append("--disable-blink-features=*")
    arms.extend(("--log-level=*", "--test-type=*", "--headless=*"))
    return "|".join(arms)


STRIP_AUTOMATION_ARGS_BASH = f"""
_untrace_filtered=()
_untrace_skip_next=0
for arg in "$@"; do
  if [ "$_untrace_skip_next" = "1" ]; then
    _untrace_skip_next=0
    continue
  fi
  case "$arg" in
    {_chromedriver_strip_case_pattern()})
      continue
      ;;
    --disable-blink-features)
      _untrace_skip_next=1
      continue
      ;;
    --headless)
      _untrace_skip_next=1
      continue
      ;;
    --test-type)
      _untrace_skip_next=1
      continue
      ;;
    --log-level)
      _untrace_skip_next=1
      continue
      ;;
  esac
  _untrace_filtered+=("$arg")
done
"""


def chrome_real_binary() -> str:
    real = chrome_real_path()
    if os.path.isfile(real):
        return real
    return CHROME_BINARY


def build_chrome_wrapper_script(
    flags: list[str] | None = None,
    *,
    chrome_real: str | None = None,
    random_profile: bool = False,
) -> str:
    if chrome_real is None:
        chrome_real_line = (
            f'CHROME_REAL="$(dirname "$(readlink -f "$0")")/{CHROME_REAL_NAME}"'
        )
    else:
        chrome_real_line = f'CHROME_REAL="{chrome_real}"'

    if random_profile:
        manual_branch = f"""{RANDOM_DIR_BASH}
{STRIP_AUTOMATION_ARGS_BASH}
  _read_launch_flags
  exec -a "$0" "${{_untrace_runner[@]}}" "${{_untrace_filtered[@]}}" --user-data-dir="$RANDOM_DIR" "${{_untrace_headless_extras[@]}}" "${{_untrace_launch_flags[@]}}" """
    else:
        manual_branch = """  _seed_untrace_extension "${HOME}/.config/google-chrome"
  _read_launch_flags
  exec -a "$0" "${_untrace_runner[@]}" "${_untrace_launch_flags[@]}" "$@" """

    return (
        "#!/bin/bash\n"
        f"{chrome_real_line}\n"
        + f"""
{UNTRACE_BEGIN}
{SEED_EXTENSION_BASH}
{READ_LAUNCH_FLAGS_BASH}
{AUTOMATION_DETECT_BASH}
{HEADLESS_DETECT_BASH}
{CHROME_RUNNER_BASH}
if [ "$UNTRACE_AUTOMATION" = "1" ]; then
{PARSE_USER_DATA_DIR_BASH}
  _seed_untrace_extension "$_untrace_user_data_dir"
{STRIP_AUTOMATION_ARGS_BASH}
  _read_launch_flags
  exec -a "$0" "${{_untrace_runner[@]}}" "${{_untrace_filtered[@]}}" "${{_untrace_headless_extras[@]}}" "${{_untrace_launch_flags[@]}}"
else
{manual_branch}
fi
{UNTRACE_END}
"""
    )


def _strip_legacy_launcher_patch(content: str) -> str:
    for pattern in (
        rf"\n{re.escape(UNTRACE_BEGIN)}[\s\S]*?{re.escape(UNTRACE_END)}\n",
        rf"\n{re.escape(UNTRACE_BEGIN)}[\s\S]*?exec -a \"\$0\" \"\$HERE/chrome\"[^\n]*\n",
        r'\n# === Random user-data-dir per launch ===[\s\S]*?exec -a "\$0" "\$HERE/chrome"[^\n]*\n',
    ):
        if re.search(pattern, content):
            return re.sub(pattern, f"\n{ORIGINAL_LINE}\n", content)
    return content


def restore_google_chrome_launcher() -> bool:
    if not os.path.isfile(CHROME_SCRIPT):
        return False
    content = read_script_linux()
    if UNTRACE_BEGIN not in content and not is_legacy_launcher_patched_linux(content):
        return False

    bpath = backup_path_linux()
    if os.path.isfile(bpath):
        shutil.copy2(bpath, CHROME_SCRIPT)
    else:
        content = _strip_legacy_launcher_patch(content)
        with open(CHROME_SCRIPT, "w") as f:
            f.write(content)
    os.chmod(CHROME_SCRIPT, 0o755)
    return True


def backup_chrome_launcher_if_needed() -> None:
    bpath = backup_path_linux()
    if os.path.isfile(bpath) or not os.path.isfile(CHROME_SCRIPT):
        return
    shutil.copy2(CHROME_SCRIPT, bpath)
    os.chmod(bpath, 0o755)


def backup_chrome_binary_if_needed() -> None:
    chrome_real = chrome_real_path()
    if os.path.isfile(chrome_real):
        return
    if not os.path.isfile(CHROME_BINARY):
        print(f"Error: {CHROME_BINARY} not found.", file=sys.stderr)
        sys.exit(1)
    with open(CHROME_BINARY, "rb") as handle:
        if not handle.read(4).startswith(b"\x7fELF"):
            print(
                f"Error: {CHROME_BINARY} is not the original binary "
                f"and {chrome_real} is missing.",
                file=sys.stderr,
            )
            sys.exit(1)
    shutil.move(CHROME_BINARY, chrome_real)


def install_chrome_binary_wrapper(
    flags: list[str], *, random_profile: bool = False
) -> None:
    backup_chrome_binary_if_needed()
    wrapper = build_chrome_wrapper_script(flags, random_profile=random_profile)
    with open(CHROME_BINARY, "w") as handle:
        handle.write(wrapper)
    os.chmod(CHROME_BINARY, 0o755)


def remove_chrome_binary_wrapper() -> None:
    chrome_real = chrome_real_path()
    if not os.path.isfile(chrome_real):
        return
    if os.path.isfile(CHROME_BINARY):
        os.remove(CHROME_BINARY)
    shutil.move(chrome_real, CHROME_BINARY)
    os.chmod(CHROME_BINARY, 0o755)


def _managed_untrace_roots() -> list[Path]:
    roots = list(injector.user_deploy_roots())
    if injector.SYSTEM_UNTRACE_ROOT not in roots:
        roots.append(injector.SYSTEM_UNTRACE_ROOT)
    return roots


def _effective_stealth_active() -> bool:
    if IS_WINDOWS:
        cfg = config.load()
        if not cfg.get("js_injection", True):
            return False
        return injector.is_windows_webstore_extension_registered()
    for root in _managed_untrace_roots():
        manifest = root / "extension" / "manifest.json"
        if not manifest.is_file():
            continue
        cfg_path = root / "config.json"
        if cfg_path.is_file():
            try:
                data = json.loads(cfg_path.read_text())
            except (json.JSONDecodeError, OSError):
                data = {}
            if not data.get("js_injection", True):
                continue
        return True
    return False


def _sync_config_to_managed_roots(cfg: dict) -> None:
    prior = injector._active_root
    for root in _managed_untrace_roots():
        if not root.is_dir() and root != injector.SYSTEM_UNTRACE_ROOT:
            continue
        injector.use_untrace_root(root)
        root.mkdir(parents=True, exist_ok=True)
        config.save(cfg)
    if prior is not None:
        injector.use_untrace_root(prior)


def _chrome_wrapper_installed() -> bool:
    if IS_WINDOWS:
        chrome = find_chrome_windows()
        if not chrome:
            return False
        return os.path.isfile(os.path.join(os.path.dirname(chrome), REAL_EXE_NAME))
    if is_chrome_wrapped_linux():
        return True
    return any((root / "chrome").is_file() for root in injector.user_deploy_roots())


def _chromedriver_patch_active() -> bool:
    for binary in chromedriver_patch.find_chromedriver_binaries():
        try:
            if chromedriver_patch.is_patched(binary.read_bytes()):
                return True
        except OSError:
            continue
    return False


def _selenium_manager_patch_active() -> bool:
    return selenium_manager_patch.any_patched()


def _apply_chromedriver_patch(cfg: dict) -> None:
    if cfg.get("chromedriver_patch", True):
        patched = chromedriver_patch.patch_all_chromedrivers()
        if patched:
            print(f"Patched {len(patched)} chromedriver binary(s).")
        if not IS_WINDOWS:
            sm_patched = selenium_manager_patch.patch_all_selenium_managers()
            if sm_patched:
                print(f"Patched {len(sm_patched)} selenium-manager binary(s).")
    else:
        unpatched = chromedriver_patch.unpatch_all_chromedrivers()
        if unpatched:
            print(f"Unpatched {len(unpatched)} chromedriver binary(s).")
        if not IS_WINDOWS:
            sm_unpatched = selenium_manager_patch.unpatch_all_selenium_managers()
            if sm_unpatched:
                print(f"Unpatched {len(sm_unpatched)} selenium-manager binary(s).")


def _disable_stealth_at_roots(cfg: dict, roots: list[Path]) -> None:
    prior = injector._active_root
    for root in roots:
        injector.use_untrace_root(root)
        root.mkdir(parents=True, exist_ok=True)
        config.save(cfg)
        injector.remove()
    if prior is not None:
        injector.use_untrace_root(prior)


def _print_active_features(cfg: dict | None = None) -> None:
    if cfg is None:
        cfg = config.load()
    wrapper_enabled = (
        bool(cfg.get("chrome_wrapper", True)) and _chrome_wrapper_installed()
    )
    flags_enabled = bool(cfg.get("chrome_flags", True)) and wrapper_enabled
    chromedriver_enabled = _chromedriver_patch_active()
    ok, bad = "OK", "OFF"
    print(f"{ok if _effective_stealth_active() else bad} Stealth")
    print(f"{ok if flags_enabled else bad} Flags")
    print(f"{ok if wrapper_enabled else bad} Chrome wrapper")
    print(f"{ok if chromedriver_enabled else bad} Chromedriver patch")
    if not IS_WINDOWS:
        selenium_manager_enabled = _selenium_manager_patch_active()
        print(f"{ok if selenium_manager_enabled else bad} Selenium-manager patch")


def windows_gui_status() -> dict:
    cfg = config.load()
    chrome = find_chrome_windows()
    wrapper_on = bool(cfg.get("chrome_wrapper", True)) and _chrome_wrapper_installed()
    flags_on = bool(cfg.get("chrome_flags", True)) and wrapper_on
    stealth_on = _effective_stealth_active()
    chromedriver_on = _chromedriver_patch_active()
    features = [
        {"id": "stealth", "label": "Anti-detection", "on": stealth_on},
        {"id": "flags", "label": "Clean profiles", "on": flags_on},
        {"id": "wrapper", "label": "Browser", "on": wrapper_on},
        {"id": "chromedriver", "label": "Automation", "on": chromedriver_on},
    ]
    any_on = any(f["on"] for f in features)
    return {
        "chrome_found": bool(chrome),
        "installed": wrapper_on or any_on,
        "features": features,
        "can_install": bool(chrome),
        "can_uninstall": wrapper_on or any_on,
    }


def _installed_wrapper_stale() -> list[str]:
    issues: list[str] = []
    if not is_chrome_wrapped_linux():
        return issues

    try:
        content = open(CHROME_BINARY, "r", encoding="utf-8").read()
    except OSError:
        return issues

    if "_read_launch_flags" not in content:
        issues.append(
            "system Chrome wrapper is stale (missing dynamic launch.flags); "
            "re-run: sudo python -m untrace --install --stealth --flags --chromedriver"
        )

    for line in content.splitlines():
        if "exec " not in line or "CHROME_REAL" not in line:
            continue
        if "--disable-blink-features=AutomationControlled" in line:
            issues.append(
                "wrapper still passes unsupported --disable-blink-features=AutomationControlled; re-run install"
            )
        break
    return issues


def status_linux():
    print("Patched" if is_chrome_wrapped_linux() else "Not patched")
    print(f"Active untrace root: {injector.get_untrace_root()}")
    print()
    _print_active_features()
    for issue in _installed_wrapper_stale():
        print(f"Warning: {issue}")
    if not is_chrome_wrapped_linux():
        print("Hint: run once with sudo: python -m untrace --install --stealth --flags")


def _resolve_install_config(
    *,
    stealth: bool = False,
    flags: bool = False,
    chromedriver: bool = False,
) -> dict:
    cfg = config.resolve_install_features(
        stealth=stealth,
        flags=flags,
        chromedriver=chromedriver,
    )
    config.save(cfg)
    return cfg


def deploy_user_chrome_wrapper(
    launch_flags: list[str],
    *,
    deploy_root: Path | None = None,
    random_profile: bool = False,
) -> Path:
    root = deploy_root or injector.USER_UNTRACE_ROOT
    wrapper = root / "chrome"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    script = build_chrome_wrapper_script(
        launch_flags,
        chrome_real=chrome_real_binary(),
        random_profile=random_profile,
    )
    wrapper.write_text(script)
    os.chmod(wrapper, 0o755)
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        link = root / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to("chrome")
    if root in injector.user_deploy_roots():
        _chown_to_sudo_user(root)
    return wrapper


def _refresh_user_wrappers(cfg: dict, launch_flags: list[str]) -> None:
    random_profile = bool(cfg.get("chrome_flags", False))
    for root in injector.user_deploy_roots():
        deploy_user_chrome_wrapper(
            launch_flags,
            deploy_root=root,
            random_profile=random_profile,
        )


def install_linux(
    *, stealth: bool = False, flags: bool = False, chromedriver: bool = False
):
    require_root()
    injector.use_system_root()
    cfg = _resolve_install_config(
        stealth=stealth, flags=flags, chromedriver=chromedriver
    )
    _sync_config_to_managed_roots(cfg)

    if cfg.get("js_injection", True):
        scripts = list(DEFAULT_CHROME_SCRIPTS)
        injector.setup(scripts, CHROME_SCRIPTS)
    else:
        roots = [root for root in _managed_untrace_roots() if root.is_dir()]
        _disable_stealth_at_roots(cfg, roots)

    restore_google_chrome_launcher()
    launch_flags = chrome_launch_flags()
    _sync_launch_flags(launch_flags)

    if cfg.get("chrome_wrapper", True):
        backup_chrome_launcher_if_needed()
        backup_chrome_binary_if_needed()
        install_chrome_binary_wrapper(
            launch_flags,
            random_profile=bool(cfg.get("chrome_flags", False)),
        )
    elif is_chrome_wrapped_linux():
        remove_chrome_binary_wrapper()

    _refresh_user_wrappers(cfg, launch_flags)
    _apply_chromedriver_patch(cfg)

    print()
    _print_active_features(cfg)
    if cfg.get("js_injection", True) and not injector.is_installed():
        print(
            "Warning: extension files missing under /etc/untrace after install.",
            file=sys.stderr,
        )


def _untrace_present() -> bool:
    if is_chrome_wrapped_linux() or os.path.isfile(backup_path_linux()):
        return True
    if any(root.is_dir() for root in injector.user_deploy_roots()):
        return True
    if _chromedriver_patch_active():
        return True
    return _selenium_manager_patch_active()


def uninstall_linux():
    require_root()
    if not _untrace_present():
        print("No untrace patch found — nothing to restore.", file=sys.stderr)
        sys.exit(1)

    injector.use_system_root()

    if is_chrome_wrapped_linux():
        remove_chrome_binary_wrapper()

    bpath = backup_path_linux()
    if os.path.isfile(bpath):
        shutil.copy2(bpath, CHROME_SCRIPT)
        os.chmod(CHROME_SCRIPT, 0o755)
        os.remove(bpath)

    restore_google_chrome_launcher()
    injector.remove()
    config.clear()

    removed_deploys = injector.remove_user_deploys()
    if removed_deploys:
        paths = ", ".join(str(root) for root in removed_deploys)
        print(f"Removed user deploy: {paths}")

    unpatched_drivers = chromedriver_patch.unpatch_all_chromedrivers()
    if unpatched_drivers:
        print(f"Unpatched {len(unpatched_drivers)} chromedriver(s).")
    unpatched_managers = selenium_manager_patch.unpatch_all_selenium_managers()
    if unpatched_managers:
        print(f"Unpatched {len(unpatched_managers)} selenium-manager(s).")
    print("Uninstalled.")


REAL_EXE_NAME = "chrome_real.exe"

CSHARP_TEMPLATE = r"""using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

class ChromeWrapper
{
    static readonly string RealExe = "__REAL_EXE__";
    static readonly string[] ExtraFlags = new string[] { __FLAGS__ };
    static readonly string[] StripExact = new string[] { __STRIP_EXACT__ };
    static readonly string[] StripPrefixes = new string[] { __STRIP_PREFIXES__ };
    static readonly bool RandomProfile = __RANDOM_PROFILE__;
    static readonly bool ServeStealth = __SERVE_STEALTH__;
    static readonly string ExtId = "__EXT_ID__";
    static readonly string TemplateDir = @"__TEMPLATE_DIR__";
    const int WarmupMs = 15000;

    // Kill chrome_real when chromedriver kills this wrapper.
    static class KillOnCloseJob
    {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetInformationJobObject(
            IntPtr hJob, int jobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        const int JobObjectExtendedLimitInformation = 9;
        const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;

        [StructLayout(LayoutKind.Sequential)]
        struct IO_COUNTERS
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        static readonly IntPtr JobHandle = CreateAndConfigure();

        static IntPtr CreateAndConfigure()
        {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero)
                return IntPtr.Zero;

            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            IntPtr infoPtr = Marshal.AllocHGlobal(length);
            try
            {
                Marshal.StructureToPtr(info, infoPtr, false);
                if (!SetInformationJobObject(
                        job, JobObjectExtendedLimitInformation, infoPtr, (uint)length))
                {
                    return IntPtr.Zero;
                }
            }
            finally
            {
                Marshal.FreeHGlobal(infoPtr);
            }
            return job;
        }

        public static void Track(Process process)
        {
            if (JobHandle == IntPtr.Zero || process == null)
                return;
            try
            {
                AssignProcessToJobObject(JobHandle, process.Handle);
            }
            catch { }
        }
    }

    static bool IsAutomation(string[] args)
    {
        for (int i = 0; i < args.Length; i++)
        {
            string arg = args[i];
            if (arg.StartsWith("--remote-debugging-port")
                || arg.StartsWith("--test-type=")
                || arg == "--test-type"
                || arg == "--enable-automation"
                || arg.StartsWith("--disable-automatio"))
                return true;
        }
        return false;
    }

    static bool ShouldStrip(string arg)
    {
        for (int i = 0; i < StripExact.Length; i++)
            if (arg == StripExact[i]) return true;
        for (int i = 0; i < StripPrefixes.Length; i++)
            if (arg.StartsWith(StripPrefixes[i])) return true;
        if (arg.StartsWith("--disable-blink-features=")) return true;
        if (arg.StartsWith("--log-level=")) return true;
        if (arg.StartsWith("--test-type=")) return true;
        return false;
    }

    static bool TakesSeparateValue(string arg)
    {
        return arg == "--disable-blink-features"
            || arg == "--test-type"
            || arg == "--log-level";
    }

    static List<string> FilterArgs(string[] args)
    {
        var filtered = new List<string>();
        for (int i = 0; i < args.Length; i++)
        {
            string arg = args[i];
            if (ShouldStrip(arg)) continue;
            if (TakesSeparateValue(arg))
            {
                if (i + 1 < args.Length) i++;
                continue;
            }
            filtered.Add(arg);
        }
        return filtered;
    }

    static string QuoteArg(string arg)
    {
        if (arg.Length == 0) return "\"\"";
        bool needQuotes = false;
        for (int i = 0; i < arg.Length; i++)
        {
            char c = arg[i];
            if (c == ' ' || c == '\t' || c == '"' || c == '\n' || c == '\v')
            {
                needQuotes = true;
                break;
            }
        }
        if (!needQuotes) return arg;

        var sb = new StringBuilder();
        sb.Append('"');
        int backslashes = 0;
        for (int i = 0; i < arg.Length; i++)
        {
            char c = arg[i];
            if (c == '\\')
            {
                backslashes++;
                continue;
            }
            if (c == '"')
            {
                sb.Append('\\', backslashes * 2 + 1);
                sb.Append('"');
                backslashes = 0;
                continue;
            }
            if (backslashes > 0)
            {
                sb.Append('\\', backslashes);
                backslashes = 0;
            }
            sb.Append(c);
        }
        if (backslashes > 0) sb.Append('\\', backslashes * 2);
        sb.Append('"');
        return sb.ToString();
    }

    static string FindUserDataDir(List<string> args)
    {
        for (int i = 0; i < args.Count; i++)
        {
            string arg = args[i];
            if (arg.StartsWith("--user-data-dir="))
                return arg.Substring("--user-data-dir=".Length).Trim('"');
            if (arg == "--user-data-dir" && i + 1 < args.Count)
                return args[i + 1].Trim('"');
        }
        return null;
    }

    static bool StealthExtensionReady(string userDataDir)
    {
        if (string.IsNullOrEmpty(userDataDir) || string.IsNullOrEmpty(ExtId))
            return false;
        string secure = Path.Combine(userDataDir, "Default", "Secure Preferences");
        if (File.Exists(secure))
        {
            try
            {
                string text = File.ReadAllText(secure);
                if (text.IndexOf(ExtId) >= 0)
                    return true;
            }
            catch { }
        }
        return false;
    }

    static void KillProcessTree(Process proc)
    {
        if (proc == null)
            return;
        try
        {
            var kill = new ProcessStartInfo
            {
                FileName = "taskkill",
                Arguments = "/F /T /PID " + proc.Id,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            Process killer = Process.Start(kill);
            if (killer != null)
                killer.WaitForExit(10000);
        }
        catch { }
        try
        {
            if (!proc.HasExited)
                proc.Kill();
        }
        catch { }
    }

    static bool ShouldSkipCopyName(string name)
    {
        if (string.Equals(name, "lockfile", StringComparison.OrdinalIgnoreCase))
            return true;
        if (string.Equals(name, "DevToolsActivePort", StringComparison.OrdinalIgnoreCase))
            return true;
        if (name.StartsWith("Singleton", StringComparison.OrdinalIgnoreCase))
            return true;
        return false;
    }

    static void CopyProfileTree(string src, string dst)
    {
        Directory.CreateDirectory(dst);
        foreach (string dir in Directory.GetDirectories(src, "*", SearchOption.AllDirectories))
        {
            string rel = dir.Substring(src.Length).TrimStart('\\', '/');
            Directory.CreateDirectory(Path.Combine(dst, rel));
        }
        foreach (string file in Directory.GetFiles(src, "*", SearchOption.AllDirectories))
        {
            string name = Path.GetFileName(file);
            if (ShouldSkipCopyName(name))
                continue;
            string rel = file.Substring(src.Length).TrimStart('\\', '/');
            string destFile = Path.Combine(dst, rel);
            Directory.CreateDirectory(Path.GetDirectoryName(destFile));
            File.Copy(file, destFile, true);
        }
        string lockPath = Path.Combine(dst, "lockfile");
        if (File.Exists(lockPath))
        {
            try { File.Delete(lockPath); } catch { }
        }
    }

    static void WarmupStealthProfile(string userDataDir)
    {
        if (string.IsNullOrEmpty(userDataDir) || StealthExtensionReady(userDataDir))
            return;

        Directory.CreateDirectory(userDataDir);
        var psi = new ProcessStartInfo
        {
            FileName = RealExe,
            Arguments = string.Join(" ", new string[] {
                QuoteArg("--user-data-dir=" + userDataDir),
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-gpu",
                QuoteArg("about:blank"),
            }),
            UseShellExecute = false,
        };

        Process warmup = null;
        try
        {
            warmup = Process.Start(psi);
            if (warmup == null)
                return;
            KillOnCloseJob.Track(warmup);
            int waited = 0;
            while (waited < WarmupMs)
            {
                if (StealthExtensionReady(userDataDir))
                    break;
                Thread.Sleep(200);
                waited += 200;
            }
            if (waited < WarmupMs)
                Thread.Sleep(Math.Min(5000, WarmupMs - waited));
        }
        catch { }
        finally
        {
            KillProcessTree(warmup);
            if (warmup != null)
            {
                try { warmup.WaitForExit(5000); } catch { }
                try { warmup.Dispose(); } catch { }
            }
            try
            {
                var killReal = new ProcessStartInfo
                {
                    FileName = "taskkill",
                    Arguments = "/F /IM chrome_real.exe /T",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                Process kr = Process.Start(killReal);
                if (kr != null)
                    kr.WaitForExit(15000);
                var killChrome = new ProcessStartInfo
                {
                    FileName = "taskkill",
                    Arguments = "/F /IM chrome.exe /T",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                Process kc = Process.Start(killChrome);
                if (kc != null)
                    kc.WaitForExit(15000);
            }
            catch { }
        }
    }

    static void EnsureTemplateProfile()
    {
        if (string.IsNullOrEmpty(TemplateDir) || StealthExtensionReady(TemplateDir))
            return;

        Mutex mutex = null;
        bool owned = false;
        try
        {
            mutex = new Mutex(false, "Local\\UntraceChromeProfileTemplate");
            owned = mutex.WaitOne(WarmupMs + 30000);
            if (StealthExtensionReady(TemplateDir))
                return;
            WarmupStealthProfile(TemplateDir);
        }
        catch { }
        finally
        {
            if (owned && mutex != null)
            {
                try { mutex.ReleaseMutex(); } catch { }
            }
            if (mutex != null)
            {
                try { mutex.Dispose(); } catch { }
            }
        }
    }

    // Template once, then copy into each --user-data-dir (DevTools-safe).
    static void EnsureWarmedProfile(string userDataDir, bool automation)
    {
        if (string.IsNullOrEmpty(userDataDir) || StealthExtensionReady(userDataDir))
            return;

        EnsureTemplateProfile();
        if (StealthExtensionReady(TemplateDir))
        {
            try
            {
                CopyProfileTree(TemplateDir, userDataDir);
                if (StealthExtensionReady(userDataDir))
                    return;
            }
            catch { }
        }
        if (!automation)
            WarmupStealthProfile(userDataDir);
    }

    static string NewRandomProfileDir()
    {
        string tempBase = Path.Combine(Path.GetTempPath(), "chrome_random_profiles");
        Directory.CreateDirectory(tempBase);
        string randomDir = Path.Combine(
            tempBase, "profile_" + Path.GetRandomFileName().Replace(".", ""));
        Directory.CreateDirectory(randomDir);
        return randomDir;
    }

    static void RemoveUserDataDirArgs(List<string> args)
    {
        for (int i = args.Count - 1; i >= 0; i--)
        {
            string arg = args[i];
            if (arg.StartsWith("--user-data-dir="))
            {
                args.RemoveAt(i);
                continue;
            }
            if (arg == "--user-data-dir")
            {
                if (i + 1 < args.Count)
                    args.RemoveAt(i + 1);
                args.RemoveAt(i);
            }
        }
    }

    static void SetUserDataDir(List<string> args, string dir)
    {
        RemoveUserDataDirArgs(args);
        args.Add("--user-data-dir=" + dir);
    }

    static bool IsUnderChromeRandomProfiles(string path)
    {
        if (string.IsNullOrEmpty(path))
            return false;
        string norm = path.Replace('/', '\\').ToLowerInvariant();
        return norm.IndexOf("\\chrome_random_profiles\\") >= 0
            || norm.EndsWith("\\chrome_random_profiles");
    }

    static bool CreateJunction(string linkPath, string targetPath)
    {
        try
        {
            if (Directory.Exists(linkPath))
                Directory.Delete(linkPath, true);
            else if (File.Exists(linkPath))
                File.Delete(linkPath);

            var psi = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = "/c mklink /J "
                    + QuoteArg(linkPath) + " " + QuoteArg(targetPath),
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            Process p = Process.Start(psi);
            if (p == null)
                return false;
            p.WaitForExit(15000);
            return p.ExitCode == 0 && Directory.Exists(linkPath);
        }
        catch
        {
            return false;
        }
    }

    static void Main(string[] args)
    {
        bool automation = IsAutomation(args);
        List<string> finalArgs = automation ? FilterArgs(args) : new List<string>(args);

        string existingDir = FindUserDataDir(finalArgs);
        string profileDir = null;

        if (automation || RandomProfile)
        {
            if (IsUnderChromeRandomProfiles(existingDir))
            {
                profileDir = existingDir;
            }
            else
            {
                profileDir = NewRandomProfileDir();
                if (automation && !string.IsNullOrEmpty(existingDir))
                {
                    if (!CreateJunction(existingDir, profileDir))
                        SetUserDataDir(finalArgs, profileDir);
                }
                else
                {
                    SetUserDataDir(finalArgs, profileDir);
                }
            }
        }

        for (int i = 0; i < ExtraFlags.Length; i++)
            finalArgs.Add(ExtraFlags[i]);

        string userDataDir = profileDir ?? FindUserDataDir(finalArgs);
        if (ServeStealth && !string.IsNullOrEmpty(userDataDir))
            EnsureWarmedProfile(userDataDir, automation);

        var quoted = new string[finalArgs.Count];
        for (int i = 0; i < finalArgs.Count; i++)
            quoted[i] = QuoteArg(finalArgs[i]);

        var psi = new ProcessStartInfo
        {
            FileName = RealExe,
            Arguments = string.Join(" ", quoted),
            UseShellExecute = false,
        };

        Process proc = Process.Start(psi);
        if (proc == null)
            Environment.Exit(1);

        KillOnCloseJob.Track(proc);

        if (automation || ServeStealth)
        {
            proc.WaitForExit();
            KillProcessTree(proc);
            Environment.Exit(proc.ExitCode);
        }
    }
}
"""


def is_admin_windows() -> bool:
    try:
        import ctypes

        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def ensure_admin_windows() -> None:
    if not IS_WINDOWS or is_admin_windows():
        return
    import ctypes

    if getattr(sys, "frozen", False):
        path = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
        workdir = str(Path(sys.executable).resolve().parent)
    else:
        path = sys.executable
        params = subprocess.list2cmdline(["-m", "untrace", *sys.argv[1:]])
        workdir = str(Path(__file__).resolve().parent.parent)
    rc = int(
        ctypes.windll.shell32.ShellExecuteW(None, "runas", path, params, workdir, 1)
    )
    if rc <= 32:
        raise SystemExit("Administrator approval is required.")
    raise SystemExit(0)


def find_chrome_windows():
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        )
        path, _ = winreg.QueryValueEx(key, "")
        if path and os.path.isfile(path):
            return path
    except OSError:
        pass

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def find_csc():
    candidates = []
    for base in (
        r"C:\Windows\Microsoft.NET\Framework64",
        r"C:\Windows\Microsoft.NET\Framework",
    ):
        candidates.extend(glob.glob(os.path.join(base, "v*", "csc.exe")))
    candidates.sort(reverse=True)
    return candidates[0] if candidates else None


def _csharp_string_array(values: list[str] | tuple[str, ...]) -> str:
    if not values:
        return ""
    return ", ".join(
        '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"' for v in values
    )


def build_wrapper_source(real_exe_path: str, *, random_profile: bool = False) -> str:
    real_exe_escaped = real_exe_path.replace("\\", "\\\\")
    cfg = config.load()
    cfg_flags = chrome_launch_flags()
    # Windows: keep --enable-automation (required with remote-debugging-port).
    strip_exact = [f for f in CHROMEDRIVER_STRIP_FLAGS if f != "--enable-automation"]
    strip_prefixes = (
        "--disable-blink-features=",
        "--log-level=",
        "--test-type=",
    )
    serve_stealth = bool(cfg.get("js_injection", True)) and IS_WINDOWS
    template_dir = str(
        injector.SYSTEM_UNTRACE_ROOT / "chrome_profile_template"
    ).replace('"', '""')

    src = CSHARP_TEMPLATE.replace("__REAL_EXE__", real_exe_escaped)
    src = src.replace("__FLAGS__", _csharp_string_array(cfg_flags))
    src = src.replace("__STRIP_EXACT__", _csharp_string_array(strip_exact))
    src = src.replace("__STRIP_PREFIXES__", _csharp_string_array(strip_prefixes))
    src = src.replace("__RANDOM_PROFILE__", "true" if random_profile else "false")
    src = src.replace("__SERVE_STEALTH__", "true" if serve_stealth else "false")
    src = src.replace("__EXT_ID__", injector.WEBSTORE_EXTENSION_ID)
    src = src.replace("__TEMPLATE_DIR__", template_dir)
    return src


def windows_profile_template_dir() -> Path:
    return injector.SYSTEM_UNTRACE_ROOT / "chrome_profile_template"


def windows_profile_template_ready() -> bool:
    secure = windows_profile_template_dir() / "Default" / "Secure Preferences"
    if not secure.is_file():
        return False
    try:
        return injector.WEBSTORE_EXTENSION_ID in secure.read_text(
            encoding="utf-8", errors="ignore"
        )
    except OSError:
        return False


def _kill_windows_chrome_processes() -> None:
    for image in ("chrome_real.exe", "chrome.exe"):
        subprocess.run(
            ["taskkill", "/F", "/IM", image, "/T"],
            capture_output=True,
            check=False,
        )


def warm_windows_profile_template(real_exe: str) -> bool:
    if windows_profile_template_ready():
        return True
    if not os.path.isfile(real_exe):
        return False

    template = windows_profile_template_dir()
    template.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            real_exe,
            f"--user-data-dir={template}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-gpu",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            if windows_profile_template_ready():
                break
            time.sleep(0.2)
        else:
            time.sleep(5)
    finally:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        _kill_windows_chrome_processes()
    return windows_profile_template_ready()


def compile_wrapper(
    real_exe_path: str, output_path: str, *, random_profile: bool = False
) -> bool:
    csc = find_csc()
    if not csc:
        print(
            "Error: csc.exe not found. .NET Framework may be missing.", file=sys.stderr
        )
        return False

    src = build_wrapper_source(real_exe_path, random_profile=random_profile)
    tmp_dir = tempfile.mkdtemp(prefix="chrome_wrapper_")
    src_path = os.path.join(tmp_dir, "ChromeWrapper.cs")

    with open(src_path, "w") as f:
        f.write(src)

    result = subprocess.run(
        [csc, "/nologo", "/target:winexe", f"/out:{output_path}", src_path],
        capture_output=True,
        text=True,
    )
    shutil.rmtree(tmp_dir, ignore_errors=True)

    if result.returncode != 0:
        print("Error: compilation failed:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return False
    return True


def status_windows():
    chrome_path = find_chrome_windows()
    if not chrome_path:
        print("chrome.exe not found")
        return

    chrome_dir = os.path.dirname(chrome_path)
    real_exe = os.path.join(chrome_dir, REAL_EXE_NAME)

    if os.path.isfile(real_exe):
        print("Patched")
    else:
        print("Not patched")
    print()
    _print_active_features()


def install_windows(
    *, stealth: bool = False, flags: bool = False, chromedriver: bool = False
):
    chrome_path = find_chrome_windows()
    if not chrome_path:
        print("Error: could not locate chrome.exe", file=sys.stderr)
        sys.exit(1)

    _kill_windows_chrome_processes()

    chrome_dir = os.path.dirname(chrome_path)
    real_exe = os.path.join(chrome_dir, REAL_EXE_NAME)

    cfg = _resolve_install_config(
        stealth=stealth, flags=flags, chromedriver=chromedriver
    )
    print(
        "Warning: Smart App Control / WDAC may block the unsigned Chrome wrapper"
        + (
            " or patched chromedriver (WinError 4551)"
            if cfg.get("chromedriver_patch", False)
            else ""
        )
        + ".",
        file=sys.stderr,
    )
    print()

    injector.remove()

    if cfg.get("js_injection", True):
        try:
            injector.register_windows_webstore_extension()
        except (OSError, RuntimeError) as exc:
            print(
                "Failed to install stealth extension on Windows. "
                "Run as Administrator and check network access to the Chrome Web Store.",
                file=sys.stderr,
            )
            print(exc, file=sys.stderr)
            sys.exit(1)

    already_patched = os.path.isfile(real_exe)
    random_profile = bool(cfg.get("chrome_flags", False))
    want_wrapper = bool(
        cfg.get("chrome_wrapper", True)
        or cfg.get("chrome_flags", False)
        or cfg.get("js_injection", False)
    )

    if want_wrapper:
        if not already_patched:
            try:
                os.rename(chrome_path, real_exe)
            except PermissionError:
                print(
                    "Permission denied. Run as Administrator and close Chrome first.",
                    file=sys.stderr,
                )
                sys.exit(1)
        if not compile_wrapper(real_exe, chrome_path, random_profile=random_profile):
            print("Error: compilation failed.", file=sys.stderr)
            if not already_patched:
                print("Rolling back...", file=sys.stderr)
                os.rename(real_exe, chrome_path)
            sys.exit(1)
        if cfg.get("js_injection", True) and not warm_windows_profile_template(
            real_exe
        ):
            print(
                "Warning: could not warm Chrome profile template; "
                "extension may install on first launch instead.",
                file=sys.stderr,
            )
    elif already_patched:
        try:
            os.remove(chrome_path)
            os.rename(real_exe, chrome_path)
        except PermissionError:
            print(
                "Permission denied. Run as Administrator and close Chrome first.",
                file=sys.stderr,
            )
            sys.exit(1)

    _apply_chromedriver_patch(cfg)

    print()
    _print_active_features(cfg)


def uninstall_windows():
    chrome_path = find_chrome_windows()
    if not chrome_path:
        print("Error: could not locate chrome.exe", file=sys.stderr)
        sys.exit(1)

    _kill_windows_chrome_processes()

    chrome_dir = os.path.dirname(chrome_path)
    real_exe = os.path.join(chrome_dir, REAL_EXE_NAME)

    if os.path.isfile(real_exe):
        try:
            os.remove(chrome_path)
            os.rename(real_exe, chrome_path)
        except PermissionError:
            print(
                "Permission denied. Run as Administrator and close Chrome first.",
                file=sys.stderr,
            )
            sys.exit(1)

    injector.remove()
    template = windows_profile_template_dir()
    if template.is_dir():
        shutil.rmtree(template, ignore_errors=True)
    config.clear()
    unpatched_drivers = chromedriver_patch.unpatch_all_chromedrivers()
    if unpatched_drivers:
        print(f"Unpatched {len(unpatched_drivers)} chromedriver(s).")
    print("Uninstalled.")


def install(*, stealth: bool = False, flags: bool = False, chromedriver: bool = False):
    kwargs = {"stealth": stealth, "flags": flags, "chromedriver": chromedriver}
    install_windows(**kwargs) if IS_WINDOWS else install_linux(**kwargs)


def uninstall():
    uninstall_windows() if IS_WINDOWS else uninstall_linux()


def status():
    status_windows() if IS_WINDOWS else status_linux()


def main():
    parser = argparse.ArgumentParser(
        description="Force Chrome to launch with extra flags + random --user-data-dir each time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  sudo python3 -m untrace --install --stealth --flags --chromedriver\n"
            "  pytest tests/test_chromedriver.py"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true")
    group.add_argument("--uninstall", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument(
        "--gui",
        action="store_true",
        help="open the Windows install/uninstall GUI",
    )
    toggles = parser.add_argument_group("features (used with --install)")
    toggles.add_argument(
        "--stealth",
        action="store_true",
        help=(
            "enable extension / JS injection "
            "(Linux: local MV3; Windows: Chrome Web Store force-install)"
        ),
    )
    toggles.add_argument(
        "--flags",
        action="store_true",
        help="patch Chrome wrapper (launcher flags, random profile for manual launches)",
    )
    toggles.add_argument(
        "--chromedriver",
        action="store_true",
        help="patch chromedriver binaries (neutralize CDC injection)",
    )

    args = parser.parse_args()
    from untrace import applog

    cmd = " ".join(sys.argv[1:]) or "(no args)"
    applog.enable(command=cmd)

    if args.install:
        install(
            stealth=args.stealth,
            flags=args.flags,
            chromedriver=args.chromedriver,
        )
    elif args.uninstall:
        uninstall()
    elif args.status:
        status()
    elif args.gui:
        if not IS_WINDOWS:
            print("Error: --gui is Windows-only.", file=sys.stderr)
            sys.exit(1)
        from untrace.gui_windows import main as gui_main

        gui_main()


if __name__ == "__main__":
    main()
