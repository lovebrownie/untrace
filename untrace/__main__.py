#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from untrace import chromedriver, config, injector, selenium
from untrace.paths import (
    CHROME_BINARY_LINUX,
    CHROME_REAL_LINUX,
    IS_WINDOWS,
    LINUX_USER_UNTRACE_REL,
    RANDOM_PROFILES_DIRNAME,
    SYSTEM_UNTRACE_LINUX,
    chown_to_invoker,
    linux_invoking_pw,
)

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
    "media.capabilities": ("media.capabilities.js", None),
    "media.devices": ("media.devices.js", None),
    "media.audio": ("media.audio.js", None),
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
    except (subprocess.SubprocessError, OSError):
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
    return flags


def write_launch_flags(flags: list[str], root: Path) -> Path:
    path = root / LAUNCH_FLAGS_FILE
    root.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(flags) + ("\n" if flags else ""))
    path.chmod(0o644)
    if root in injector.user_deploy_roots():
        chown_to_invoker(root)
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


CHROME_SCRIPT = Path("/opt/google/chrome/google-chrome")
CHROME_BINARY = Path(CHROME_BINARY_LINUX)
CHROME_REAL_NAME = "chrome_real"
BACKUP_SUFFIX = ".bak"
ORIGINAL_LINE = 'exec -a "$0" "$HERE/chrome" "$@"'


def backup_path_linux() -> Path:
    return Path(f"{CHROME_SCRIPT}{BACKUP_SUFFIX}")


def read_script_linux() -> str:
    if not CHROME_SCRIPT.is_file():
        print(
            f"Error: {CHROME_SCRIPT} not found. Is Chrome installed?", file=sys.stderr
        )
        sys.exit(1)
    return CHROME_SCRIPT.read_text()


def chrome_real_path() -> Path:
    return Path(CHROME_REAL_LINUX)


def is_legacy_launcher_patched_linux(content: str) -> bool:
    return "--user-data-dir" in content and RANDOM_PROFILES_DIRNAME in content


def is_chrome_wrapped_linux() -> bool:
    return chrome_real_path().is_file()


UNTRACE_BEGIN = "# === UNTRACE BEGIN ==="
UNTRACE_END = "# === UNTRACE END ==="

AUTOMATION_DETECT_BASH = """
UNTRACE_AUTOMATION=0
for arg in "$@"; do
  case "$arg" in
    --remote-debugging-port*|--remote-debugging-pipe*|--test-type=webdriver|--test-type=webbrowse|--enable-automation|--disable-automatio)
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

SEED_EXTENSION_BASH = f"""
_resolve_untrace_root() {{
  if [ -n "${{UNTRACE_ROOT:-}}" ] && [ -f "${{UNTRACE_ROOT}}/seed_profile.py" ]; then
    printf '%s\\n' "$UNTRACE_ROOT"
    return 0
  fi
  if [ -f "${{HOME}}/{LINUX_USER_UNTRACE_REL}/seed_profile.py" ]; then
    printf '%s\\n' "${{HOME}}/{LINUX_USER_UNTRACE_REL}"
    return 0
  fi
  printf '%s\\n' "{SYSTEM_UNTRACE_LINUX}"
}}

_seed_untrace_extension() {{
  local pdir="$1"
  local root
  shift
  [ -n "$pdir" ] || return 0
  root="$(_resolve_untrace_root)"
  mkdir -p "$pdir"
  if "$root/seed_profile.py" "$pdir" "$@"; then
    return 0
  fi
  sleep 0.2
  if ! "$root/seed_profile.py" "$pdir" "$@"; then
    echo "[untrace] warning: extension seed failed for $pdir" >&2
  fi
}}
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

PARSE_LOAD_EXTENSION_BASH = """
_untrace_load_extensions=()
_untrace_load_ext_prev=""
_untrace_collect_load_extension_paths() {
  local csv="$1" part
  local -a parts=()
  IFS=',' read -r -a parts <<< "$csv"
  for part in "${parts[@]}"; do
    part="${part#"${part%%[![:space:]]*}"}"
    part="${part%"${part##*[![:space:]]}"}"
    [ -n "$part" ] || continue
    _untrace_load_extensions+=("$part")
  done
}
for arg in "$@"; do
  if [ "$_untrace_load_ext_prev" = "--load-extension" ]; then
    _untrace_collect_load_extension_paths "$arg"
    _untrace_load_ext_prev=""
    continue
  fi
  case "$arg" in
    --load-extension=*)
      _untrace_collect_load_extension_paths "${arg#--load-extension=}"
      ;;
    --load-extension)
      _untrace_load_ext_prev="--load-extension"
      ;;
  esac
done
"""

RANDOM_DIR_BASH = f"""
RANDOM_DIR="$(mktemp -d /tmp/{RANDOM_PROFILES_DIRNAME}/profile_XXXXXXXXXX 2>/dev/null || echo "/tmp/{RANDOM_PROFILES_DIRNAME}/profile_$(date +%s%N | sha256sum | cut -c1-16)")"
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


def _strip_automation_args_bash() -> str:
    return f"""
_untrace_filtered=()
_untrace_disable_features=()
_untrace_skip_next=0
_untrace_skip_is_disable_features=0
for arg in "$@"; do
  if [ "$_untrace_skip_next" = "1" ]; then
    _untrace_skip_next=0
    if [ "$_untrace_skip_is_disable_features" = "1" ]; then
      _untrace_skip_is_disable_features=0
      _untrace_add_disable_features "$arg"
    fi
    continue
  fi
  case "$arg" in
    {_chromedriver_strip_case_pattern()})
      continue
      ;;
    --disable-features=*)
      _untrace_add_disable_features "${{arg#--disable-features=}}"
      continue
      ;;
    --disable-features)
      _untrace_skip_next=1
      _untrace_skip_is_disable_features=1
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
    --disable-extensions)
      continue
      ;;
    --disable-extensions-except)
      _untrace_skip_next=1
      continue
      ;;
    --disable-extensions-except=*)
      continue
      ;;
  esac
  _untrace_filtered+=("$arg")
done
"""


MERGE_DISABLE_FEATURES_BASH = """
_untrace_add_disable_features() {
  local csv="$1" feat seen f
  local -a feats=()
  IFS=',' read -r -a feats <<< "$csv"
  for feat in "${feats[@]}"; do
    feat="${feat#"${feat%%[![:space:]]*}"}"
    feat="${feat%"${feat##*[![:space:]]}"}"
    [ -n "$feat" ] || continue
    case "$feat" in
      IgnoreDuplicateNavs|Prewarm) continue ;;
    esac
    seen=0
    for f in "${_untrace_disable_features[@]}"; do
      if [ "$f" = "$feat" ]; then
        seen=1
        break
      fi
    done
    [ "$seen" = "0" ] || continue
    _untrace_disable_features+=("$feat")
  done
}

_untrace_merge_disable_features() {
  local out=() line joined
  _untrace_add_disable_features "DisableLoadExtensionCommandLineSwitch"
  for line in "${_untrace_launch_flags[@]}"; do
    case "$line" in
      --disable-features=*)
        _untrace_add_disable_features "${line#--disable-features=}"
        ;;
      *)
        out+=("$line")
        ;;
    esac
  done
  _untrace_launch_flags=("${out[@]}")
  if [ "${#_untrace_disable_features[@]}" -gt 0 ]; then
    joined=$(IFS=,; printf '%s' "${_untrace_disable_features[*]}")
    _untrace_filtered+=("--disable-features=$joined")
  fi
}
"""


def chrome_real_binary() -> str:
    real = chrome_real_path()
    if real.is_file():
        return str(real)
    return str(CHROME_BINARY)


def build_chrome_wrapper_script(
    *,
    chrome_real: str | None = None,
    random_profile: bool = False,
) -> str:
    strip_args = _strip_automation_args_bash()

    if chrome_real is None:
        chrome_real_line = (
            f'CHROME_REAL="$(dirname "$(readlink -f "$0")")/{CHROME_REAL_NAME}"'
        )
    else:
        chrome_real_line = f'CHROME_REAL="{chrome_real}"'

    if random_profile:
        manual_branch = f"""{RANDOM_DIR_BASH}
{strip_args}
  _read_launch_flags
  _untrace_merge_disable_features
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
{MERGE_DISABLE_FEATURES_BASH}
{AUTOMATION_DETECT_BASH}
{HEADLESS_DETECT_BASH}
{CHROME_RUNNER_BASH}
if [ "$UNTRACE_AUTOMATION" = "1" ]; then
{PARSE_USER_DATA_DIR_BASH}
{PARSE_LOAD_EXTENSION_BASH}
  _seed_untrace_extension "$_untrace_user_data_dir" "${{_untrace_load_extensions[@]}}"
{strip_args}
  _read_launch_flags
  _untrace_merge_disable_features
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
    if not CHROME_SCRIPT.is_file():
        return False
    content = read_script_linux()
    if UNTRACE_BEGIN not in content and not is_legacy_launcher_patched_linux(content):
        return False

    bpath = backup_path_linux()
    if bpath.is_file():
        shutil.copy2(bpath, CHROME_SCRIPT)
    else:
        content = _strip_legacy_launcher_patch(content)
        CHROME_SCRIPT.write_text(content)
    CHROME_SCRIPT.chmod(0o755)
    return True


def backup_chrome_launcher_if_needed() -> None:
    bpath = backup_path_linux()
    if bpath.is_file() or not CHROME_SCRIPT.is_file():
        return
    shutil.copy2(CHROME_SCRIPT, bpath)
    bpath.chmod(0o755)


def backup_chrome_binary_if_needed() -> None:
    chrome_real = chrome_real_path()
    if chrome_real.is_file():
        return
    if not CHROME_BINARY.is_file():
        print(f"Error: {CHROME_BINARY} not found.", file=sys.stderr)
        sys.exit(1)
    with CHROME_BINARY.open("rb") as handle:
        if not handle.read(4).startswith(b"\x7fELF"):
            print(
                f"Error: {CHROME_BINARY} is not the original binary "
                f"and {chrome_real} is missing.",
                file=sys.stderr,
            )
            sys.exit(1)
    shutil.move(CHROME_BINARY, chrome_real)


def install_chrome_binary_wrapper(*, random_profile: bool = False) -> None:
    backup_chrome_binary_if_needed()
    wrapper = build_chrome_wrapper_script(random_profile=random_profile)
    CHROME_BINARY.write_text(wrapper)
    CHROME_BINARY.chmod(0o755)


def remove_chrome_binary_wrapper() -> None:
    chrome_real = chrome_real_path()
    if not chrome_real.is_file():
        return
    if CHROME_BINARY.is_file():
        CHROME_BINARY.unlink()
    shutil.move(chrome_real, CHROME_BINARY)
    CHROME_BINARY.chmod(0o755)


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
    prior = injector._active_root
    try:
        for root in _managed_untrace_roots():
            if not (root / "extension" / "manifest.json").is_file():
                continue
            injector.use_untrace_root(root)
            if config.load().get("js_injection", True):
                return True
    finally:
        _restore_untrace_root(prior)
    return False


def _restore_untrace_root(prior: Path | None) -> None:
    if prior is not None:
        injector.use_untrace_root(prior)
    else:
        injector.clear_untrace_root_override()


def _sync_config_to_managed_roots(cfg: dict) -> None:
    prior = injector._active_root
    try:
        for root in _managed_untrace_roots():
            if not root.is_dir() and root != injector.SYSTEM_UNTRACE_ROOT:
                continue
            injector.use_untrace_root(root)
            root.mkdir(parents=True, exist_ok=True)
            config.save(cfg)
    finally:
        _restore_untrace_root(prior)


def _chrome_wrapper_installed() -> bool:
    if IS_WINDOWS:
        chrome = find_chrome_windows()
        if not chrome:
            return False
        return (Path(chrome).parent / REAL_EXE_NAME).is_file()
    if is_chrome_wrapped_linux():
        return True
    return any((root / "chrome").is_file() for root in injector.user_deploy_roots())


def _chromedriver_patch_active() -> bool:
    for binary in chromedriver.find_chromedriver_binaries():
        try:
            if chromedriver.is_patched(binary.read_bytes()):
                return True
        except OSError:
            continue
    return False


def _selenium_manager_patch_active() -> bool:
    return selenium.any_patched()


def _apply_chromedriver_patch(cfg: dict) -> None:
    from untrace import applog

    if cfg.get("chromedriver_patch", True):
        patched = chromedriver.patch_all_chromedrivers()
        if patched:
            applog.write(f"Patched {len(patched)} chromedriver binary(s): {patched}")
        if not IS_WINDOWS:
            sm_patched = selenium.patch_all_selenium_managers()
            if sm_patched:
                applog.write(
                    f"Patched {len(sm_patched)} selenium-manager binary(s): {sm_patched}"
                )
    else:
        unpatched = chromedriver.unpatch_all_chromedrivers()
        if unpatched:
            applog.write(
                f"Unpatched {len(unpatched)} chromedriver binary(s): {unpatched}"
            )
        if not IS_WINDOWS:
            sm_unpatched = selenium.unpatch_all_selenium_managers()
            if sm_unpatched:
                applog.write(
                    f"Unpatched {len(sm_unpatched)} selenium-manager binary(s): "
                    f"{sm_unpatched}"
                )


def _disable_stealth_at_roots(cfg: dict, roots: list[Path]) -> None:
    prior = injector._active_root
    try:
        for root in roots:
            injector.use_untrace_root(root)
            root.mkdir(parents=True, exist_ok=True)
            config.save(cfg)
            injector.remove()
    finally:
        _restore_untrace_root(prior)


def _print_active_features(cfg: dict | None = None) -> None:
    if cfg is None:
        cfg = config.load()
    wrapper_enabled = (
        bool(cfg.get("chrome_wrapper", True)) and _chrome_wrapper_installed()
    )
    flags_enabled = bool(cfg.get("chrome_flags", True)) and wrapper_enabled
    chromedriver_enabled = _chromedriver_patch_active()
    ok, bad = "OK", "OFF"
    print(f"{ok if _effective_stealth_active() else bad} Stealth extension")
    print(f"{ok if flags_enabled else bad} Random profiles")
    print(f"{ok if wrapper_enabled else bad} Chrome launch wrapper")
    print(f"{ok if chromedriver_enabled else bad} Chromedriver CDC patch")
    if not IS_WINDOWS:
        selenium_manager_enabled = _selenium_manager_patch_active()
        print(f"{ok if selenium_manager_enabled else bad} Selenium-manager redirect")


def gui_status() -> dict:
    cfg = config.load()
    if IS_WINDOWS:
        chrome_found = bool(find_chrome_windows())
    else:
        chrome_found = CHROME_BINARY.is_file() or chrome_real_path().is_file()
    wrapper_on = bool(cfg.get("chrome_wrapper", True)) and _chrome_wrapper_installed()
    flags_on = bool(cfg.get("chrome_flags", True)) and wrapper_on
    stealth_on = _effective_stealth_active()
    chromedriver_on = _chromedriver_patch_active()
    features = [
        {"id": "stealth", "label": "Stealth extension", "on": stealth_on},
        {"id": "flags", "label": "Random profiles", "on": flags_on},
        {"id": "wrapper", "label": "Chrome launch wrapper", "on": wrapper_on},
        {
            "id": "chromedriver",
            "label": "Chromedriver CDC patch",
            "on": chromedriver_on,
        },
    ]
    any_on = any(f["on"] for f in features)
    return {
        "chrome_found": chrome_found,
        "installed": wrapper_on or any_on,
        "features": features,
        "can_install": chrome_found,
        "can_uninstall": wrapper_on or any_on,
    }


def _installed_wrapper_stale() -> list[str]:
    issues: list[str] = []
    if not is_chrome_wrapped_linux():
        return issues

    try:
        content = CHROME_BINARY.read_text(encoding="utf-8")
    except OSError:
        return issues

    if "_read_launch_flags" not in content:
        issues.append(
            "system Chrome wrapper is stale (missing dynamic launch.flags); "
            "re-run: sudo python -m untrace --install "
            "--stealth-extension --launch-wrapper --chromedriver-cdc"
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
    from untrace import applog

    applog.write(
        f"status: wrapped={is_chrome_wrapped_linux()} "
        f"root={injector.get_untrace_root()}"
    )
    for issue in _installed_wrapper_stale():
        applog.write(f"status: warning: {issue}")
    _print_active_features()


def _resolve_install_config(
    *,
    stealth_extension: bool = False,
    launch_wrapper: bool = False,
    chromedriver_cdc: bool = False,
) -> dict:
    cfg = config.resolve_install_features(
        stealth_extension=stealth_extension,
        launch_wrapper=launch_wrapper,
        chromedriver_cdc=chromedriver_cdc,
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
        chrome_real=chrome_real_binary(),
        random_profile=random_profile,
    )
    wrapper.write_text(script)
    wrapper.chmod(0o755)
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
        chown_to_invoker(root)
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
    *,
    stealth_extension: bool = False,
    launch_wrapper: bool = False,
    chromedriver_cdc: bool = False,
):
    injector.use_system_root()
    try:
        cfg = _resolve_install_config(
            stealth_extension=stealth_extension,
            launch_wrapper=launch_wrapper,
            chromedriver_cdc=chromedriver_cdc,
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
                random_profile=bool(cfg.get("chrome_flags", False)),
            )
        elif is_chrome_wrapped_linux():
            remove_chrome_binary_wrapper()

        _refresh_user_wrappers(cfg, launch_flags)
        _apply_chromedriver_patch(cfg)

        from untrace import applog

        applog.write(
            "install: stealth="
            f"{cfg.get('js_injection')} flags={cfg.get('chrome_flags')} "
            f"wrapper={cfg.get('chrome_wrapper')} "
            f"chromedriver={cfg.get('chromedriver_patch')}"
        )
        print()
        _print_active_features(cfg)
        if cfg.get("js_injection", True) and not injector.is_installed():
            msg = "Warning: extension files missing under /etc/untrace after install."
            applog.write(f"install: {msg}")
            print(msg, file=sys.stderr)
    finally:
        injector.clear_untrace_root_override()


def _untrace_present() -> bool:
    if is_chrome_wrapped_linux() or backup_path_linux().is_file():
        return True
    if any(
        injector.user_deploy_has_payload(root) for root in injector.user_deploy_roots()
    ):
        return True
    if _chromedriver_patch_active():
        return True
    return _selenium_manager_patch_active()


def uninstall_linux():
    from untrace import applog

    if not _untrace_present():
        applog.write("uninstall: no untrace patch found — nothing to restore")
        applog.close()
        injector.remove_user_deploys()
        print("Uninstalled")
        return

    injector.use_system_root()
    try:
        if is_chrome_wrapped_linux():
            remove_chrome_binary_wrapper()
            applog.write("uninstall: removed Chrome binary wrapper")

        bpath = backup_path_linux()
        if bpath.is_file():
            shutil.copy2(bpath, CHROME_SCRIPT)
            CHROME_SCRIPT.chmod(0o755)
            bpath.unlink()
            applog.write(f"uninstall: restored launcher from {bpath}")

        restore_google_chrome_launcher()
        injector.remove()
        config.clear()
        applog.write("uninstall: cleared system extension root and config")

        unpatched_drivers = chromedriver.unpatch_all_chromedrivers()
        if unpatched_drivers:
            applog.write(
                f"uninstall: unpatched {len(unpatched_drivers)} chromedriver(s): "
                f"{unpatched_drivers}"
            )
        unpatched_managers = selenium.unpatch_all_selenium_managers()
        if unpatched_managers:
            applog.write(
                f"uninstall: unpatched {len(unpatched_managers)} selenium-manager(s): "
                f"{unpatched_managers}"
            )
        applog.write("uninstall: complete; removing user deploy roots (incl. log)")
        applog.close()
        injector.remove_user_deploys()
        print("Uninstalled")
    finally:
        injector.clear_untrace_root_override()


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
    static readonly List<string> DisableFeatures = new List<string>();

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

    // Terminate processes through the Win32 API instead of spawning
    // taskkill.exe, so no console window can ever flash from this
    // (windowed) wrapper.
    static class WinProcessKill
    {
        [DllImport("kernel32.dll")]
        static extern IntPtr CreateToolhelp32Snapshot(
            uint dwFlags, uint th32ProcessID);

        [DllImport("kernel32.dll")]
        static extern bool Process32FirstW(
            IntPtr hSnapshot, ref PROCESSENTRY32W lppe);

        [DllImport("kernel32.dll")]
        static extern bool Process32NextW(
            IntPtr hSnapshot, ref PROCESSENTRY32W lppe);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenProcess(
            uint dwDesiredAccess, bool bInheritHandle, uint dwProcessId);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool TerminateProcess(
            IntPtr hProcess, uint uExitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint WaitForSingleObject(
            IntPtr hHandle, uint dwMilliseconds);

        [DllImport("kernel32.dll")]
        static extern bool CloseHandle(IntPtr hObject);

        const uint TH32CS_SNAPPROCESS = 0x00000002;
        const uint PROCESS_TERMINATE = 0x00000001;
        const uint SYNCHRONIZE = 0x00100000;

        [StructLayout(LayoutKind.Sequential)]
        struct PROCESSENTRY32W
        {
            public uint dwSize;
            public uint cntUsage;
            public uint th32ProcessID;
            public IntPtr th32DefaultHeapID;
            public uint th32ModuleID;
            public uint cntThreads;
            public uint th32ParentProcessID;
            public int pcPriClassBase;
            public uint dwFlags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
            public string szExeFile;
        }

        public static void KillTree(uint rootPid)
        {
            var children = new Dictionary<uint, List<uint>>();
            IntPtr snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if (snapshot != IntPtr.Zero && snapshot != (IntPtr)(-1))
            {
                try
                {
                    var entry = new PROCESSENTRY32W();
                    entry.dwSize = (uint)Marshal.SizeOf(typeof(PROCESSENTRY32W));
                    bool more = Process32FirstW(snapshot, ref entry);
                    while (more)
                    {
                        List<uint> list;
                        if (!children.TryGetValue(entry.th32ParentProcessID, out list))
                        {
                            list = new List<uint>();
                            children[entry.th32ParentProcessID] = list;
                        }
                        list.Add(entry.th32ProcessID);
                        more = Process32NextW(snapshot, ref entry);
                    }
                }
                finally
                {
                    CloseHandle(snapshot);
                }
            }

            var order = new List<uint>();
            var stack = new Stack<uint>();
            stack.Push(rootPid);
            while (stack.Count > 0)
            {
                uint pid = stack.Pop();
                order.Add(pid);
                List<uint> kids;
                if (children.TryGetValue(pid, out kids))
                {
                    for (int i = 0; i < kids.Count; i++)
                        stack.Push(kids[i]);
                }
            }
            order.Reverse(); // children first, parents last

            IntPtr rootHandle = IntPtr.Zero;
            for (int i = 0; i < order.Count; i++)
            {
                uint pid = order[i];
                IntPtr handle = OpenProcess(
                    PROCESS_TERMINATE | SYNCHRONIZE, false, pid);
                if (handle == IntPtr.Zero)
                    continue;
                try
                {
                    TerminateProcess(handle, 1);
                }
                catch { }
                if (pid == rootPid)
                    rootHandle = handle;
                else
                    CloseHandle(handle);
            }

            if (rootHandle != IntPtr.Zero)
            {
                try { WaitForSingleObject(rootHandle, 10000); } catch { }
                CloseHandle(rootHandle);
            }
        }

        public static void KillByName(string imageName)
        {
            string needle = imageName.ToLowerInvariant();
            var matches = new List<uint>();
            IntPtr snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if (snapshot == IntPtr.Zero || snapshot == (IntPtr)(-1))
                return;
            try
            {
                var entry = new PROCESSENTRY32W();
                entry.dwSize = (uint)Marshal.SizeOf(typeof(PROCESSENTRY32W));
                bool more = Process32FirstW(snapshot, ref entry);
                while (more)
                {
                    if (entry.szExeFile != null
                        && entry.szExeFile.ToLowerInvariant() == needle)
                    {
                        matches.Add(entry.th32ProcessID);
                    }
                    more = Process32NextW(snapshot, ref entry);
                }
            }
            finally
            {
                CloseHandle(snapshot);
            }
            for (int i = 0; i < matches.Count; i++)
                KillTree(matches[i]);
        }
    }

    static bool IsAutomation(string[] args)
    {
        for (int i = 0; i < args.Length; i++)
        {
            string arg = args[i];
            if (arg.StartsWith("--remote-debugging-port")
                || arg.StartsWith("--remote-debugging-pipe")
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
            || arg == "--log-level"
            || arg == "--disable-extensions-except";
    }

    static void AddDisableFeatures(string csv)
    {
        if (string.IsNullOrEmpty(csv))
            return;
        string[] parts = csv.Split(',');
        for (int i = 0; i < parts.Length; i++)
        {
            string feat = parts[i].Trim();
            if (feat.Length == 0)
                continue;
            if (feat == "IgnoreDuplicateNavs" || feat == "Prewarm")
                continue;
            bool seen = false;
            for (int j = 0; j < DisableFeatures.Count; j++)
            {
                if (DisableFeatures[j] == feat)
                {
                    seen = true;
                    break;
                }
            }
            if (!seen)
                DisableFeatures.Add(feat);
        }
    }

    static void CollectDisableFeaturesArg(string arg)
    {
        if (arg.StartsWith("--disable-features="))
            AddDisableFeatures(arg.Substring("--disable-features=".Length));
    }

    static void MergeDisableFeatures(List<string> args)
    {
        for (int i = args.Count - 1; i >= 0; i--)
        {
            string arg = args[i];
            if (arg.StartsWith("--disable-features="))
            {
                CollectDisableFeaturesArg(arg);
                args.RemoveAt(i);
                continue;
            }
            if (arg == "--disable-features")
            {
                if (i + 1 < args.Count)
                {
                    AddDisableFeatures(args[i + 1]);
                    args.RemoveAt(i + 1);
                }
                args.RemoveAt(i);
            }
        }
        AddDisableFeatures("DisableLoadExtensionCommandLineSwitch");
        if (DisableFeatures.Count > 0)
            args.Add("--disable-features=" + string.Join(",", DisableFeatures));
    }

    static List<string> FilterArgs(string[] args)
    {
        var filtered = new List<string>();
        for (int i = 0; i < args.Length; i++)
        {
            string arg = args[i];
            if (arg.StartsWith("--disable-features="))
            {
                CollectDisableFeaturesArg(arg);
                continue;
            }
            if (arg == "--disable-features")
            {
                if (i + 1 < args.Length)
                {
                    i++;
                    AddDisableFeatures(args[i]);
                }
                continue;
            }
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
            WinProcessKill.KillTree((uint)proc.Id);
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
                WinProcessKill.KillByName("chrome_real.exe");
                WinProcessKill.KillByName("chrome.exe");
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
    static void EnsureWarmedProfile(string userDataDir)
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

        MergeDisableFeatures(finalArgs);

        string userDataDir = profileDir ?? FindUserDataDir(finalArgs);
        if (ServeStealth && !string.IsNullOrEmpty(userDataDir))
            EnsureWarmedProfile(userDataDir);

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


def hide_windows_console() -> None:
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
        kernel32.FreeConsole()
    except Exception:
        pass


def ensure_admin_windows(*, show_console: bool = True) -> None:
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
    n_show = 1 if show_console else 0
    rc = int(
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", path, params, workdir, n_show
        )
    )
    if rc <= 32:
        raise SystemExit("Administrator approval is required.")
    raise SystemExit(0)


def _linux_display_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR"):
        val = os.environ.get(key)
        if val:
            env[key] = val
    if "DISPLAY" in env and "XAUTHORITY" not in env:
        home = os.environ.get("HOME")
        if home:
            xauth = Path(home) / ".Xauthority"
            if xauth.is_file():
                env["XAUTHORITY"] = str(xauth)
    return env


def _linux_adopt_display_env() -> None:
    pw = linux_invoking_pw()
    if pw is None:
        return
    runtime = Path(f"/run/user/{pw.pw_uid}")
    if not os.environ.get("XAUTHORITY"):
        xauth_candidates = [
            Path(pw.pw_dir) / ".Xauthority",
            runtime / "gdm" / "Xauthority",
            runtime / "Xauthority",
            *sorted(runtime.glob(".mutter-Xwaylandauth*")),
        ]
        for xauth in xauth_candidates:
            if xauth.is_file():
                os.environ["XAUTHORITY"] = str(xauth)
                break
    if not os.environ.get("DISPLAY"):
        for display in (":0", ":1"):
            if (Path("/tmp/.X11-unix") / f"X{display[1:]}").exists():
                os.environ["DISPLAY"] = display
                break
    if not os.environ.get("WAYLAND_DISPLAY") and (runtime / "wayland-0").exists():
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
    if not os.environ.get("XDG_RUNTIME_DIR") and runtime.is_dir():
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)


def ensure_linux_root() -> None:
    if IS_WINDOWS:
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        _linux_adopt_display_env()
        return
    if getattr(sys, "frozen", False):
        # AppImage FUSE mounts are not executable by root — elevate the .AppImage itself.
        appimage = os.environ.get("APPIMAGE")
        executable = (
            appimage if appimage and Path(appimage).is_file() else sys.executable
        )
        argv = [executable, *sys.argv[1:]]
    else:
        argv = [sys.executable, "-m", "untrace", *sys.argv[1:]]
    display_env = _linux_display_env()
    if os.environ.get("APPIMAGE"):
        display_env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")
    env_assign = [f"{key}={value}" for key, value in display_env.items()]
    for launcher in ("pkexec", "sudo"):
        try:
            cmd = (
                [launcher, "env", *env_assign, *argv]
                if env_assign
                else [launcher, *argv]
            )
            raise SystemExit(subprocess.call(cmd))
        except FileNotFoundError:
            continue
    raise SystemExit("Root privileges are required. Re-run with sudo.")


def ensure_privileges(*, show_console: bool = True) -> None:
    if IS_WINDOWS:
        ensure_admin_windows(show_console=show_console)
    else:
        ensure_linux_root()


def find_chrome_windows() -> str | None:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        )
        path, _ = winreg.QueryValueEx(key, "")
        if path and Path(path).is_file():
            return str(path)
    except OSError:
        pass

    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        candidates.append(
            Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def find_csc() -> str | None:
    candidates: list[Path] = []
    for base in (
        Path(r"C:\Windows\Microsoft.NET\Framework64"),
        Path(r"C:\Windows\Microsoft.NET\Framework"),
    ):
        if base.is_dir():
            candidates.extend(base.glob("v*/csc.exe"))
    candidates.sort(key=lambda p: str(p), reverse=True)
    return str(candidates[0]) if candidates else None


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
    strip_exact.append("--disable-extensions")
    strip_prefixes = [
        "--disable-blink-features=",
        "--log-level=",
        "--test-type=",
        "--disable-extensions-except=",
    ]
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


def _windows_process_snapshot() -> list[tuple[int, int, str]]:
    """Return (pid, parent_pid, exe_name) for every process in the snapshot."""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (-1, 0):
        return []

    processes: list[tuple[int, int, str]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            exe_name = ctypes.wstring_at(ctypes.addressof(entry.szExeFile))
            processes.append((entry.th32ProcessID, entry.th32ParentProcessID, exe_name))
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def _windows_process_tree_pids(root_pid: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for pid, parent_pid, _exe_name in _windows_process_snapshot():
        children.setdefault(parent_pid, []).append(pid)

    pids = {root_pid}
    stack = [root_pid]
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            if child not in pids:
                pids.add(child)
                stack.append(child)
    return pids


def _terminate_windows_process_tree(root_pid: int, timeout_ms: int = 10000) -> None:
    """Terminate a process and its descendants via the Win32 API."""
    import ctypes
    from ctypes import wintypes

    PROCESS_TERMINATE = 0x0001
    SYNCHRONIZE = 0x00100000

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    children: dict[int, list[int]] = {}
    for pid, parent_pid, _exe_name in _windows_process_snapshot():
        children.setdefault(parent_pid, []).append(pid)

    order: list[int] = []
    stack = [root_pid]
    while stack:
        pid = stack.pop()
        order.append(pid)
        stack.extend(children.get(pid, []))
    order.reverse()  # children first, so parents die last

    root_handle = None
    for pid in order:
        handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
        if not handle:
            continue
        try:
            kernel32.TerminateProcess(handle, 1)
        finally:
            if pid == root_pid:
                root_handle = handle
            else:
                kernel32.CloseHandle(handle)
    if root_handle is not None:
        try:
            kernel32.WaitForSingleObject(root_handle, timeout_ms)
        finally:
            kernel32.CloseHandle(root_handle)


def _kill_windows_chrome_processes() -> None:
    images = ("chrome_real.exe", "chrome.exe")
    targets = [
        pid
        for pid, _parent_pid, exe_name in _windows_process_snapshot()
        if exe_name.lower() in images
    ]
    for pid in targets:
        _terminate_windows_process_tree(pid)


def _minimize_windows_for_pids(pids: set[int]) -> None:
    if not pids:
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    SW_SHOWMINNOACTIVE = 7
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)
        return True

    callback = WNDENUMPROC(_enum)
    user32.EnumWindows(callback, 0)


def warm_windows_profile_template(real_exe: str) -> bool:
    if windows_profile_template_ready():
        return True
    if not Path(real_exe).is_file():
        return False

    template = windows_profile_template_dir()
    template.mkdir(parents=True, exist_ok=True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 7  # SW_SHOWMINNOACTIVE
    proc = subprocess.Popen(
        [
            real_exe,
            f"--user-data-dir={template}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-gpu",
            "--start-minimized",
            "--window-position=-32000,-32000",
            "--window-size=800,600",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startup,
    )
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            _minimize_windows_for_pids(_windows_process_tree_pids(proc.pid))
            if windows_profile_template_ready():
                break
            time.sleep(0.2)
        else:
            time.sleep(5)
    finally:
        _terminate_windows_process_tree(proc.pid)
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
    tmp_dir = Path(tempfile.mkdtemp(prefix="chrome_wrapper_"))
    src_path = tmp_dir / "ChromeWrapper.cs"
    src_path.write_text(src)

    result = subprocess.run(
        [csc, "/nologo", "/target:winexe", f"/out:{output_path}", str(src_path)],
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
    from untrace import applog

    chrome_path = find_chrome_windows()
    if not chrome_path:
        applog.write("status: chrome.exe not found")
        print("chrome.exe not found")
        return

    real_exe = Path(chrome_path).parent / REAL_EXE_NAME
    applog.write(f"status: wrapped={real_exe.is_file()} chrome={chrome_path}")
    _print_active_features()


def install_windows(
    *,
    stealth_extension: bool = False,
    launch_wrapper: bool = False,
    chromedriver_cdc: bool = False,
):
    chrome_path = find_chrome_windows()
    if not chrome_path:
        print("Error: could not locate chrome.exe", file=sys.stderr)
        sys.exit(1)

    _kill_windows_chrome_processes()

    chrome = Path(chrome_path)
    real_exe = chrome.parent / REAL_EXE_NAME

    from untrace import applog

    cfg = _resolve_install_config(
        stealth_extension=stealth_extension,
        launch_wrapper=launch_wrapper,
        chromedriver_cdc=chromedriver_cdc,
    )
    sac_warn = (
        "Warning: Smart App Control / WDAC may block the unsigned Chrome wrapper"
        + (
            " or patched chromedriver (WinError 4551)"
            if cfg.get("chromedriver_patch", False)
            else ""
        )
        + "."
    )
    applog.write(f"install: {sac_warn}")
    print(sac_warn, file=sys.stderr)
    print()

    injector.remove()

    if cfg.get("js_injection", True):
        try:
            injector.register_windows_webstore_extension()
            applog.write("install: registered Windows Web Store extension")
        except (OSError, RuntimeError) as exc:
            msg = (
                "Failed to install stealth extension on Windows. "
                "Run as Administrator and check network access to the Chrome Web Store."
            )
            applog.write(f"install: {msg} ({exc!r})")
            print(msg, file=sys.stderr)
            print(exc, file=sys.stderr)
            sys.exit(1)

    already_patched = real_exe.is_file()
    random_profile = bool(cfg.get("chrome_flags", False))
    want_wrapper = bool(
        cfg.get("chrome_wrapper", True)
        or cfg.get("chrome_flags", False)
        or cfg.get("js_injection", False)
    )

    if want_wrapper:
        if not already_patched:
            try:
                chrome.rename(real_exe)
            except PermissionError:
                print(
                    "Permission denied. Run as Administrator and close Chrome first.",
                    file=sys.stderr,
                )
                sys.exit(1)
        if not compile_wrapper(
            str(real_exe), str(chrome), random_profile=random_profile
        ):
            print("Error: compilation failed.", file=sys.stderr)
            if not already_patched:
                print("Rolling back...", file=sys.stderr)
                real_exe.rename(chrome)
            sys.exit(1)
        if cfg.get("js_injection", True) and not warm_windows_profile_template(
            str(real_exe)
        ):
            print(
                "Warning: could not warm Chrome profile template; "
                "extension may install on first launch instead.",
                file=sys.stderr,
            )
    elif already_patched:
        try:
            chrome.unlink()
            real_exe.rename(chrome)
        except PermissionError:
            print(
                "Permission denied. Run as Administrator and close Chrome first.",
                file=sys.stderr,
            )
            sys.exit(1)

    _apply_chromedriver_patch(cfg)

    applog.write(
        "install: stealth="
        f"{cfg.get('js_injection')} flags={cfg.get('chrome_flags')} "
        f"wrapper={cfg.get('chrome_wrapper')} "
        f"chromedriver={cfg.get('chromedriver_patch')}"
    )
    print()
    _print_active_features(cfg)


def uninstall_windows():
    from untrace import applog

    chrome_path = find_chrome_windows()
    if not chrome_path:
        applog.write("uninstall: could not locate chrome.exe")
        print("Error: could not locate chrome.exe", file=sys.stderr)
        sys.exit(1)

    _kill_windows_chrome_processes()

    chrome = Path(chrome_path)
    real_exe = chrome.parent / REAL_EXE_NAME

    if real_exe.is_file():
        try:
            chrome.unlink()
            real_exe.rename(chrome)
            applog.write(f"uninstall: restored {chrome} from {real_exe}")
        except PermissionError as exc:
            applog.write(f"uninstall: permission denied restoring chrome: {exc!r}")
            print(
                "Permission denied. Run as Administrator and close Chrome first.",
                file=sys.stderr,
            )
            sys.exit(1)

    injector.remove()
    template = windows_profile_template_dir()
    if template.is_dir():
        shutil.rmtree(template, ignore_errors=True)
        applog.write(f"uninstall: removed profile template {template}")
    config.clear()
    unpatched_drivers = chromedriver.unpatch_all_chromedrivers()
    if unpatched_drivers:
        applog.write(
            f"uninstall: unpatched {len(unpatched_drivers)} chromedriver(s): "
            f"{unpatched_drivers}"
        )
    applog.write("uninstall: complete; removing user deploy roots (incl. log)")
    applog.close()
    injector.remove_user_deploys()
    print("Uninstalled")


def install(
    *,
    stealth_extension: bool = False,
    launch_wrapper: bool = False,
    chromedriver_cdc: bool = False,
):
    ensure_privileges()
    kwargs = {
        "stealth_extension": stealth_extension,
        "launch_wrapper": launch_wrapper,
        "chromedriver_cdc": chromedriver_cdc,
    }
    install_windows(**kwargs) if IS_WINDOWS else install_linux(**kwargs)


def uninstall():
    ensure_privileges()
    uninstall_windows() if IS_WINDOWS else uninstall_linux()


def status():
    status_windows() if IS_WINDOWS else status_linux()


def pack_extension(*, output: str | None = None, version: str | None = None) -> Path:
    from untrace.version import __version__, extension_zip_name

    root = Path(__file__).resolve().parent.parent
    ver = version or __version__
    out = Path(output) if output else root / "dist" / extension_zip_name(ver)
    path = injector.pack_extension_zip(
        out,
        list(DEFAULT_CHROME_SCRIPTS),
        CHROME_SCRIPTS,
        version=ver,
    )
    print(path)
    return path


def build_dist(*, output: str | None = None, version: str | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "build.py"
    cmd = [sys.executable, str(script)]
    if output:
        cmd.extend(["--output", str(output)])
    if version:
        cmd.extend(["--version", version])
    return subprocess.call(cmd, cwd=str(root))


def main():
    parser = argparse.ArgumentParser(
        description="Force Chrome to launch with extra flags + random --user-data-dir each time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  sudo python3 -m untrace --install "
            "--stealth-extension --launch-wrapper --chromedriver-cdc\n"
            "  python -m untrace --build\n"
            "  python -m untrace --pack-extension\n"
            "  pytest tests/test_chromedriver.py"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--install", action="store_true")
    group.add_argument("--uninstall", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument(
        "--gui",
        action="store_true",
        help="open the install/uninstall GUI",
    )
    group.add_argument(
        "--pack-extension",
        action="store_true",
        help="pack Chrome Web Store zip -> dist/untrace-injector-vX.Y.Z.zip",
    )
    group.add_argument(
        "--build",
        action="store_true",
        help=(
            "build dist artifacts: Untrace installer + extension zip "
            "(Windows Setup.exe / Linux .deb)"
        ),
    )
    toggles = parser.add_argument_group("features (used with --install)")
    toggles.add_argument(
        "--stealth-extension",
        action="store_true",
        help=(
            "MV3 stealth extension (anti-detection scripts); "
            "Linux: local pack/seed; Windows: Chrome Web Store force-install"
        ),
    )
    toggles.add_argument(
        "--launch-wrapper",
        action="store_true",
        help=(
            "Chrome launch wrapper + random profiles each launch "
            "(strips chromedriver junk, applies launcher flags)"
        ),
    )
    toggles.add_argument(
        "--chromedriver-cdc",
        action="store_true",
        help="patch chromedriver binaries (neutralize window.cdc_* injection)",
    )
    pack_opts = parser.add_argument_group("build / pack-extension")
    pack_opts.add_argument(
        "--output",
        metavar="PATH",
        help="zip output path (default: dist/untrace-injector-vX.Y.Z.zip)",
    )
    pack_opts.add_argument(
        "--version",
        metavar="VER",
        help="manifest version (default: package __version__)",
    )

    args = parser.parse_args()
    if not any(
        (
            args.install,
            args.uninstall,
            args.status,
            args.gui,
            args.pack_extension,
            args.build,
        )
    ):
        args.gui = True
    from untrace import applog

    cmd = " ".join(sys.argv[1:]) or "(no args)"
    applog.enable(command=cmd)

    if args.install:
        install(
            stealth_extension=args.stealth_extension,
            launch_wrapper=args.launch_wrapper,
            chromedriver_cdc=args.chromedriver_cdc,
        )
    elif args.uninstall:
        uninstall()
    elif args.status:
        status()
    elif args.build:
        raise SystemExit(build_dist(output=args.output, version=args.version))
    elif args.pack_extension:
        pack_extension(output=args.output, version=args.version)
    elif args.gui:
        from untrace.gui import main as gui_main

        gui_main()


if __name__ == "__main__":
    main()
