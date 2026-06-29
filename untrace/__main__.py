#!/usr/bin/env python3
import argparse
import glob
import os
import platform
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile

from untrace import config, injector

IS_WINDOWS = platform.system() == "Windows"

CHROME_FLAGS: dict[str, str] = {
    "start-maximized": "--start-maximized",
    "no-default-browser-check": "--no-default-browser-check",
    "no-first-run": "--no-first-run",
    "disable-automation-controlled": (
        "--disable-blink-features=AutomationControlled"
    ),
}

CHROME_SCRIPTS: dict[str, tuple[str, list | None]] = {
    "chrome.app": ("chrome.app.js", None),
    "chrome.runtime": ("chrome.runtime.js", [False]),
    "chrome.csi": ("chrome.csi.js", None),
    "chrome.loadTimes": ("chrome.loadTimes.js", None),
    "iframe.contentWindow": ("iframe.contentWindow.js", None),
    "media.codecs": ("media.codecs.js", None),
    "navigator.languages": ("navigator.languages.js", [["en-US", "en"]]),
    "navigator.permissions": ("navigator.permissions.js", None),
    "navigator.plugins": ("navigator.plugins.js", None),
    "navigator.vendor": ("navigator.vendor.js", ["Google Inc."]),
    "navigator.webdriver": ("navigator.webdriver.js", None),
    "sourceurl": ("sourceurl.js", None),
    "akamai": ("akamai.js", None),
    "webgl.vendor": ("webgl.vendor.js", ["Intel Inc.", "Intel Iris OpenGL Engine"]),
    "window.outerdimensions": ("window.outerdimensions.js", None),
    "hairline.fix": ("hairline.fix.js", None),
}

DEFAULT_CHROME_FLAGS: tuple[str, ...] = tuple(CHROME_FLAGS.keys())
# Optional scripts are deployed on demand; akamai/sourceurl patch native APIs in ways
# Akamai Bot Manager detects, and hairline.fix is only needed for headless layouts.
OPTIONAL_CHROME_SCRIPTS: frozenset[str] = frozenset(
    {"hairline.fix", "akamai", "sourceurl"}
)
DEFAULT_CHROME_SCRIPTS: tuple[str, ...] = tuple(
    name for name in CHROME_SCRIPTS if name not in OPTIONAL_CHROME_SCRIPTS
)


def chrome_launch_flags() -> list[str]:
    cfg = config.load()
    flags: list[str] = []
    if cfg.get("chrome_flags", True):
        flags.extend(CHROME_FLAGS[name] for name in DEFAULT_CHROME_FLAGS)
    if cfg.get("js_injection", True):
        flags.extend(injector.extension_launch_flags())
    return flags


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
    --remote-debugging-port*|--test-type=webdriver|--enable-automation)
      UNTRACE_AUTOMATION=1
      break
      ;;
  esac
done
"""

SEED_EXTENSION_BASH = f"""
_seed_untrace_extension() {{
  local pdir="$1"
  [ -n "$pdir" ] || return 0
  mkdir -p "$pdir"
  {injector.SEED_PROFILE_SCRIPT} "$pdir" || true
}}
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


def build_chrome_wrapper_script(flags: list[str]) -> str:
    flags_str = f" {flags_str}" if (flags_str := " ".join(flags)) else ""
    return (
        "#!/bin/bash\n"
        f'CHROME_REAL="$(dirname "$(readlink -f "$0")")/{CHROME_REAL_NAME}"\n'
        + f"""
{UNTRACE_BEGIN}
{SEED_EXTENSION_BASH}
{AUTOMATION_DETECT_BASH}
if [ "$UNTRACE_AUTOMATION" = "1" ]; then
{PARSE_USER_DATA_DIR_BASH}
  _seed_untrace_extension "$_untrace_user_data_dir"
  exec -a "$0" "$CHROME_REAL" "$@"{flags_str}
else
{RANDOM_DIR_BASH}
  exec -a "$0" "$CHROME_REAL" "$@" --user-data-dir="$RANDOM_DIR"{flags_str}
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


def install_chrome_binary_wrapper(flags: list[str]) -> None:
    backup_chrome_binary_if_needed()
    wrapper = build_chrome_wrapper_script(flags)
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


def _print_active_features(cfg: dict | None = None) -> None:
    cfg = config.load() if cfg is None else cfg
    js_enabled = bool(cfg.get("js_injection", True))
    flags_enabled = bool(cfg.get("chrome_flags", True))
    print(f"{'✓' if js_enabled and injector.is_installed() else '✗'} Stealth")
    print(f"{'✓' if flags_enabled else '✗'} Flags")


def status_linux():
    print("Patched" if is_chrome_wrapped_linux() else "Not patched")
    _print_active_features()


def _resolve_install_config(*, stealth: bool = False, flags: bool = False) -> dict:
    cfg = config.resolve_install_features(stealth=stealth, flags=flags)
    config.save(cfg)
    return cfg


def install_linux(*, stealth: bool = False, flags: bool = False):
    require_root()
    cfg = _resolve_install_config(stealth=stealth, flags=flags)

    already_wrapped = is_chrome_wrapped_linux()
    backup_chrome_binary_if_needed()

    if cfg.get("js_injection", True):
        scripts = list(DEFAULT_CHROME_SCRIPTS)
        injector.setup(scripts, CHROME_SCRIPTS)
    else:
        injector.remove()

    restore_google_chrome_launcher()
    launch_flags = chrome_launch_flags()
    install_chrome_binary_wrapper(launch_flags)

    print("Installed." if not already_wrapped else "Updated.")
    _print_active_features(cfg)


def uninstall_linux():
    require_root()
    if not is_chrome_wrapped_linux() and not os.path.isfile(backup_path_linux()):
        print("No untrace patch found — nothing to restore.", file=sys.stderr)
        sys.exit(1)

    remove_chrome_binary_wrapper()

    bpath = backup_path_linux()
    if os.path.isfile(bpath):
        shutil.copy2(bpath, CHROME_SCRIPT)
        os.chmod(CHROME_SCRIPT, 0o755)
        os.remove(bpath)

    restore_google_chrome_launcher()
    injector.remove()
    config.clear()
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

    launch_flags = chrome_launch_flags()

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


def install(*, stealth: bool = False, flags: bool = False):
    kwargs = {"stealth": stealth, "flags": flags}
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
            "  sudo python3 -m untrace --install\n"
            "  sudo python3 -m untrace --install --stealth\n"
            "  sudo python3 -m untrace --install --flags\n"
            "  sudo python3 -m untrace --install --stealth --flags"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true")
    group.add_argument("--uninstall", action="store_true")
    group.add_argument("--status", action="store_true")

    toggles = parser.add_argument_group("features (used with --install)")
    toggles.add_argument(
        "--stealth",
        action="store_true",
        help="install with stealth JS injection only",
    )
    toggles.add_argument(
        "--flags",
        action="store_true",
        help="install with Chrome launcher flags only",
    )

    args = parser.parse_args()

    if args.install:
        install(stealth=args.stealth, flags=args.flags)
    elif args.uninstall:
        uninstall()
    elif args.status:
        status()


if __name__ == "__main__":
    main()
