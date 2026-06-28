#!/usr/bin/env python3
import argparse
import glob
import os
import platform
import random
import shutil
import string
import subprocess
import sys
import tempfile

IS_WINDOWS = platform.system() == "Windows"

EXTRA_FLAGS = [
    "--start-maximized",
    "--no-default-browser-check",
    "--no-first-run",
]


# ---------------------------------------------------------------------------
# Helper: Generate random user data directory name
# ---------------------------------------------------------------------------
def random_user_data_dir() -> str:
    """Returns a random directory path inside the system temp folder."""
    rand_suffix = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    if IS_WINDOWS:
        base = os.path.expandvars(r"%TEMP%\chrome_random_profiles")
    else:
        base = "/tmp/chrome_random_profiles"
    path = os.path.join(base, f"profile_{rand_suffix}")
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Linux: patch the bash launcher script
# ---------------------------------------------------------------------------
CHROME_SCRIPT = "/opt/google/chrome/google-chrome"
BACKUP_SUFFIX = ".bak"
ORIGINAL_LINE = 'exec -a "$0" "$HERE/chrome" "$@"'


def backup_path_linux():
    return CHROME_SCRIPT + BACKUP_SUFFIX


def require_root():
    if os.geteuid() != 0:
        print("This action needs root. Re-run with sudo:")
        print(f" sudo {sys.argv[0]} {' '.join(sys.argv[1:])}")
        sys.exit(1)


def read_script_linux():
    if not os.path.isfile(CHROME_SCRIPT):
        print(
            f"Error: {CHROME_SCRIPT} not found. Is Chrome installed?", file=sys.stderr
        )
        sys.exit(1)
    with open(CHROME_SCRIPT, "r") as f:
        return f.read()


def is_patched_linux(content: str) -> bool:
    return "--user-data-dir" in content and "chrome_random_profiles" in content


def status_linux():
    content = read_script_linux()
    if is_patched_linux(content):
        print(
            "✅ Currently PATCHED — Chrome will launch with random --user-data-dir + extra flags"
        )
    else:
        print("➖ Not patched — Chrome launches normally")
    if os.path.isfile(backup_path_linux()):
        print(f" Backup present at: {backup_path_linux()}")
    else:
        print(" No backup found.")


def install_linux():
    require_root()
    content = read_script_linux()
    if is_patched_linux(content):
        print("Already patched with random user-data-dir.")
        return

    bpath = backup_path_linux()
    if not os.path.isfile(bpath):
        shutil.copy2(CHROME_SCRIPT, bpath)
        print(f"Backed up original to {bpath}")

    # Fixed: removed unnecessary f prefix
    random_dir_block = """
# === Random user-data-dir per launch ===
RANDOM_DIR="$(mktemp -d /tmp/chrome_random_profiles/profile_XXXXXXXXXX 2>/dev/null || echo "/tmp/chrome_random_profiles/profile_$(date +%s%N | sha256sum | cut -c1-16)")"
mkdir -p "$RANDOM_DIR"
"""

    exec_line = f'exec -a "$0" "$HERE/chrome" "$@" --user-data-dir="$RANDOM_DIR" {" ".join(EXTRA_FLAGS)}'

    patched_script = content.replace(ORIGINAL_LINE, random_dir_block + exec_line)

    with open(CHROME_SCRIPT, "w") as f:
        f.write(patched_script)
    os.chmod(CHROME_SCRIPT, 0o755)

    print(
        "✅ Patched successfully. Chrome will now use a fresh random user-data-dir on every launch."
    )
    print("Test it with: google-chrome-stable or google-chrome")


def uninstall_linux():
    require_root()
    bpath = backup_path_linux()
    if not os.path.isfile(bpath):
        print("No backup found — nothing to restore.", file=sys.stderr)
        sys.exit(1)
    shutil.copy2(bpath, CHROME_SCRIPT)
    os.chmod(CHROME_SCRIPT, 0o755)
    os.remove(bpath)
    print("✅ Restored original Chrome launch script. Backup removed.")


# ---------------------------------------------------------------------------
# Windows: C# wrapper with random user-data-dir
# ---------------------------------------------------------------------------
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
    flags_literal = ", ".join(f'"{f}"' for f in EXTRA_FLAGS)
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
        print("➖ Could not locate chrome.exe")
        return

    chrome_dir = os.path.dirname(chrome_path)
    real_exe = os.path.join(chrome_dir, REAL_EXE_NAME)

    if os.path.isfile(real_exe):
        print("✅ Currently PATCHED — random --user-data-dir + extra flags")
        print(f" Original at: {real_exe}")
    else:
        print("➖ Not patched")
        print(f" Chrome found at: {chrome_path}")


def install_windows():
    chrome_path = find_chrome_windows()
    if not chrome_path:
        print("Error: could not locate chrome.exe", file=sys.stderr)
        sys.exit(1)

    chrome_dir = os.path.dirname(chrome_path)
    real_exe = os.path.join(chrome_dir, REAL_EXE_NAME)

    if os.path.isfile(real_exe):
        print("Already patched. Run --uninstall first if you want to change flags.")
        return

    try:
        os.rename(chrome_path, real_exe)
    except PermissionError:
        print(
            "Permission denied. Run as Administrator and close Chrome first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Backed up original to {real_exe}")

    if not compile_wrapper(real_exe, chrome_path):
        print("Rolling back...", file=sys.stderr)
        os.rename(real_exe, chrome_path)
        sys.exit(1)

    print(
        "✅ Patched successfully! Chrome will now use a fresh random user-data-dir every launch."
    )


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

    print("✅ Restored original chrome.exe.")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def install():
    install_windows() if IS_WINDOWS else install_linux()


def uninstall():
    uninstall_windows() if IS_WINDOWS else uninstall_linux()


def status():
    status_windows() if IS_WINDOWS else status_linux()


def main():
    parser = argparse.ArgumentParser(
        description="Force Chrome to launch with extra flags + random --user-data-dir each time."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true")
    group.add_argument("--uninstall", action="store_true")
    group.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.install:
        install()
    elif args.uninstall:
        uninstall()
    elif args.status:
        status()


if __name__ == "__main__":
    main()
