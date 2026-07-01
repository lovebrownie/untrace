#!/usr/bin/env python3
import argparse
import glob
import json
import os
import platform
import pwd
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
from pathlib import Path

from untrace import chromedriver_patch, config, injector, selenium_manager_patch

IS_WINDOWS = platform.system() == "Windows"

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
    for root in _managed_untrace_roots():
        manifest = root / "extension" / "manifest.json"
        if not manifest.is_file():
            continue
        cfg_path = root / "config.json"
        if cfg_path.is_file():
            try:
                data = json.loads(cfg_path.read_text())
            except json.JSONDecodeError, OSError:
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
        sm_patched = selenium_manager_patch.patch_all_selenium_managers()
        if sm_patched:
            print(f"Patched {len(sm_patched)} selenium-manager binary(s).")
    else:
        unpatched = chromedriver_patch.unpatch_all_chromedrivers()
        if unpatched:
            print(f"Unpatched {len(unpatched)} chromedriver binary(s).")
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
    flags_enabled = bool(cfg.get("chrome_flags", True))
    wrapper_enabled = (
        bool(cfg.get("chrome_wrapper", True)) and _chrome_wrapper_installed()
    )
    chromedriver_enabled = _chromedriver_patch_active()
    selenium_manager_enabled = _selenium_manager_patch_active()
    print(f"{'✓' if _effective_stealth_active() else '✗'} Stealth")
    print(f"{'✓' if flags_enabled else '✗'} Flags")
    print(f"{'✓' if wrapper_enabled else '✗'} Chrome wrapper")
    print(f"{'✓' if chromedriver_enabled else '✗'} Chromedriver patch")
    print(f"{'✓' if selenium_manager_enabled else '✗'} Selenium-manager patch")


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
    _print_active_features()
    for issue in _installed_wrapper_stale():
        print(f"Warning: {issue}")
    if not is_chrome_wrapped_linux():
        print("Hint: run once with sudo: python -m untrace --install --stealth --flags")
    elif not any(
        (root / "seed_profile.py").is_file() for root in injector.user_deploy_roots()
    ):
        print(
            "Hint: python -m untrace --deploy --stealth --flags (no password) updates extension"
        )


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
        if not (root / "chrome").is_file() and not (root / "seed_profile.py").is_file():
            continue
        deploy_user_chrome_wrapper(
            launch_flags,
            deploy_root=root,
            random_profile=random_profile,
        )


def _ensure_user_deploy_writable() -> None:
    root = injector.get_untrace_root()
    if root.exists() and not os.access(root, os.W_OK):
        print(
            f"Cannot write to {root} (permission denied). "
            f"Fix ownership: sudo chown -R $USER {root}",
            file=sys.stderr,
        )
        sys.exit(1)


def deploy_linux(
    *, stealth: bool = False, flags: bool = False, chromedriver: bool = False
):
    injector.use_user_root()
    _ensure_user_deploy_writable()
    cfg = _resolve_install_config(
        stealth=stealth, flags=flags, chromedriver=chromedriver
    )

    if cfg.get("js_injection", True):
        scripts = list(DEFAULT_CHROME_SCRIPTS)
        injector.setup(scripts, CHROME_SCRIPTS)
    else:
        injector.remove()

    launch_flags = chrome_launch_flags()
    _sync_launch_flags(launch_flags, injector.user_deploy_roots())
    wrapper = deploy_user_chrome_wrapper(
        launch_flags,
        random_profile=bool(cfg.get("chrome_flags", False)),
    )

    _apply_chromedriver_patch(cfg)

    print(f"Deployed to {injector.get_untrace_root()} (no root required).")
    print(f"Selenium chrome wrapper: {wrapper}")
    _print_active_features(cfg)
    if not is_chrome_wrapped_linux():
        print(
            "Note: system Chrome wrapper not installed; Selenium uses the user wrapper above.",
            file=sys.stderr,
        )
    for issue in _installed_wrapper_stale():
        print(f"Warning: {issue}", file=sys.stderr)


def install_linux(
    *, stealth: bool = False, flags: bool = False, chromedriver: bool = False
):
    require_root()
    injector.use_system_root()
    cfg = _resolve_install_config(
        stealth=stealth, flags=flags, chromedriver=chromedriver
    )
    _sync_config_to_managed_roots(cfg)

    already_wrapped = is_chrome_wrapped_linux()

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

    print("Installed." if not already_wrapped else "Updated.")
    _print_active_features(cfg)
    if cfg.get("js_injection", True) and not injector.is_installed():
        print(
            "Warning: extension files missing under /etc/untrace after install.",
            file=sys.stderr,
        )
    active_user_deploys = [
        root
        for root in injector.user_deploy_roots()
        if (root / "seed_profile.py").is_file()
    ]
    if active_user_deploys:
        paths = ", ".join(str(root) for root in active_user_deploys)
        print(
            f"Note: user deploy takes priority over /etc/untrace ({paths}) — "
            "run python -m untrace --deploy --stealth --flags to update what Chrome uses.",
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
using System.Diagnostics;
using System.IO;
using System.Linq;

class ChromeWrapper
{
    static void Main(string[] args)
    {
        string realExe = "__REAL_EXE__";
        string[] extraFlags = new string[] { __FLAGS__ };

        // Generate random user data dir
        string tempBase = Path.Combine(Path.GetTempPath(), "chrome_random_profiles");
        Directory.CreateDirectory(tempBase);
        string randomDir = Path.Combine(tempBase, "profile_" + Path.GetRandomFileName().Replace(".", ""));
        Directory.CreateDirectory(randomDir);

        var allArgs = args.Concat(extraFlags)
                          .Concat(new[] { "--user-data-dir=" + randomDir })
                          .Select(a => "\"" + a.Replace("\"", "\\\"") + "\"");

        string argString = string.Join(" ", allArgs);

        var psi = new ProcessStartInfo
        {
            FileName = realExe,
            Arguments = argString,
            UseShellExecute = false,
        };
        Process.Start(psi);
    }
}
"""


def is_admin_windows() -> bool:
    try:
        import ctypes

        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


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


def build_wrapper_source(real_exe_path: str) -> str:
    real_exe_escaped = real_exe_path.replace("\\", "\\\\")
    flags_literal = ", ".join(f'"{f}"' for f in chrome_launch_flags())
    src = CSHARP_TEMPLATE.replace("__REAL_EXE__", real_exe_escaped)
    src = src.replace("__FLAGS__", flags_literal)
    return src


def compile_wrapper(real_exe_path: str, output_path: str) -> bool:
    csc = find_csc()
    if not csc:
        print(
            "Error: csc.exe not found. .NET Framework may be missing.", file=sys.stderr
        )
        return False

    src = build_wrapper_source(real_exe_path)
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
    _print_active_features()


def install_windows(*, stealth: bool = False, flags: bool = False):
    chrome_path = find_chrome_windows()
    if not chrome_path:
        print("Error: could not locate chrome.exe", file=sys.stderr)
        sys.exit(1)

    chrome_dir = os.path.dirname(chrome_path)
    real_exe = os.path.join(chrome_dir, REAL_EXE_NAME)

    cfg = _resolve_install_config(stealth=stealth, flags=flags)

    if cfg.get("js_injection", True):
        scripts = list(DEFAULT_CHROME_SCRIPTS)
        injector.setup(scripts, CHROME_SCRIPTS)
    else:
        injector.remove()

    already_patched = os.path.isfile(real_exe)

    if not already_patched:
        try:
            os.rename(chrome_path, real_exe)
        except PermissionError:
            print(
                "Permission denied. Run as Administrator and close Chrome first.",
                file=sys.stderr,
            )
            sys.exit(1)
    if not compile_wrapper(real_exe, chrome_path):
        print("Error: compilation failed.", file=sys.stderr)
        if not already_patched:
            print("Rolling back...", file=sys.stderr)
            os.rename(real_exe, chrome_path)
            injector.remove()
        sys.exit(1)

    print("Updated." if already_patched else "Installed.")
    _print_active_features(cfg)


def uninstall_windows():
    chrome_path = find_chrome_windows()
    if not chrome_path:
        print("Error: could not locate chrome.exe", file=sys.stderr)
        sys.exit(1)

    chrome_dir = os.path.dirname(chrome_path)
    real_exe = os.path.join(chrome_dir, REAL_EXE_NAME)

    if not os.path.isfile(real_exe):
        print("No backup found.", file=sys.stderr)
        sys.exit(1)

    try:
        os.remove(chrome_path)
        os.rename(real_exe, chrome_path)
    except PermissionError:
        print(
            "Permission denied. Run as Administrator and close Chrome first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Uninstalled.")
    injector.remove()
    config.clear()


def install(*, stealth: bool = False, flags: bool = False, chromedriver: bool = False):
    kwargs = {"stealth": stealth, "flags": flags, "chromedriver": chromedriver}
    install_windows(**kwargs) if IS_WINDOWS else install_linux(**kwargs)


def deploy(*, stealth: bool = False, flags: bool = False, chromedriver: bool = False):
    kwargs = {"stealth": stealth, "flags": flags, "chromedriver": chromedriver}
    if IS_WINDOWS:
        print("--deploy is not supported on Windows yet.", file=sys.stderr)
        sys.exit(1)
    deploy_linux(**kwargs)


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
            "  python3 -m untrace --deploy --stealth --flags --chromedriver\n"
            "  pytest tests/test_chromedriver.py"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true")
    group.add_argument("--deploy", action="store_true")
    group.add_argument("--uninstall", action="store_true")
    group.add_argument("--status", action="store_true")
    toggles = parser.add_argument_group("features (used with --install / --deploy)")
    toggles.add_argument(
        "--stealth",
        action="store_true",
        help="enable extension / JS injection only",
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

    if args.install:
        install(
            stealth=args.stealth,
            flags=args.flags,
            chromedriver=args.chromedriver,
        )
    elif args.deploy:
        deploy(
            stealth=args.stealth,
            flags=args.flags,
            chromedriver=args.chromedriver,
        )
    elif args.uninstall:
        uninstall()
    elif args.status:
        status()


if __name__ == "__main__":
    main()
