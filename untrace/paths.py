from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

BACKUP_SUFFIX = ".untrace.bak"
CHROME_REAL_LINUX = "/opt/google/chrome/chrome_real"
CHROME_BINARY_LINUX = "/opt/google/chrome/chrome"
RANDOM_PROFILES_DIRNAME = "chrome_random_profiles"
LINUX_USER_UNTRACE_REL = ".local/share/untrace"
SYSTEM_UNTRACE_LINUX = "/etc/untrace"


def user_home() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("USERPROFILE") or Path.home())
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and hasattr(os, "geteuid") and os.geteuid() == 0:
        try:
            import pwd

            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except (KeyError, ImportError):
            return Path(f"/home/{sudo_user}")
    return Path.home()


def user_untrace_root() -> Path:
    if IS_WINDOWS:
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        return Path(local) / "Untrace" if local else Path()
    return user_home() / LINUX_USER_UNTRACE_REL


def home_dirs_to_search() -> list[Path]:
    homes: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        homes.append(resolved)

    add(Path.home())
    if not IS_WINDOWS:
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            try:
                import pwd

                add(Path(pwd.getpwnam(sudo_user).pw_dir))
            except (KeyError, ImportError):
                add(Path(f"/home/{sudo_user}"))
    return homes


def assets_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def linux_invoking_pw():
    if IS_WINDOWS:
        return None
    try:
        import pwd
    except ImportError:
        return None
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return pwd.getpwnam(sudo_user)
        except KeyError:
            pass
    pkexec_uid = os.environ.get("PKEXEC_UID")
    if pkexec_uid and pkexec_uid.isdigit():
        try:
            return pwd.getpwuid(int(pkexec_uid))
        except KeyError:
            pass
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return None
    try:
        return pwd.getpwuid(os.getuid())
    except KeyError:
        return None


def chown_to_invoker(path: Path) -> None:
    if IS_WINDOWS or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    pw = linux_invoking_pw()
    if pw is None or not path.exists():
        return
    targets = [path]
    if path.is_dir():
        targets.extend(sorted(path.rglob("*"), reverse=True))
    for item in targets:
        try:
            os.chown(item, pw.pw_uid, pw.pw_gid)
        except OSError:
            pass


def backup_path_for(binary: Path) -> Path:
    return binary.parent / f"{binary.name}{BACKUP_SUFFIX}"
