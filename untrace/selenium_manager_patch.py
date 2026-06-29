from __future__ import annotations

import os
import pwd
import shutil
import sysconfig
from pathlib import Path

from untrace import injector

PATCH_MARKER = "untrace selenium-manager"
BACKUP_SUFFIX = ".untrace.bak"
WRAPPER_SCRIPT = """#!/bin/bash
# {patch_marker}
REAL="$(dirname "$(readlink -f "$0")")/{binary_name}{backup_suffix}"
USER_CHROME="${{HOME}}/.local/share/untrace/chrome"
OUT="$("$REAL" "$@" 2>/dev/null)" || exit $?
if [ ! -f "$USER_CHROME" ]; then
  printf '%s\\n' "$OUT"
  exit 0
fi
{python} -c '
import json, os, sys
data = json.load(sys.stdin)
result = data.get("result")
if isinstance(result, dict) and result.get("browser_path"):
    user = os.path.expanduser("~/.local/share/untrace/chrome")
    if os.path.isfile(user):
        result["browser_path"] = user
print(json.dumps(data))
' <<< "$OUT"
"""


def _home_dirs_to_search() -> list[Path]:
    homes: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        homes.append(resolved)

    add(Path.home())
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            add(Path(pwd.getpwnam(sudo_user).pw_dir))
        except KeyError:
            add(Path(f"/home/{sudo_user}"))
    return homes


def _selenium_manager_candidates() -> list[Path]:
    candidates: list[Path] = []
    exe = sysconfig.get_config_var("EXE") or ""

    for home in _home_dirs_to_search():
        for site_packages in (
            home / ".local" / "lib",
            home / ".local" / "share" / "uv",
        ):
            if not site_packages.is_dir():
                continue
            candidates.extend(
                site_packages.glob(
                    f"**/site-packages/selenium/webdriver/common/*/selenium-manager{exe}"
                )
            )

    try:
        import selenium.webdriver.common.selenium_manager as sm

        candidates.append(Path(sm.__file__).parent.parent / "linux" / f"selenium-manager{exe}")
    except ImportError:
        pass

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def backup_path(binary: Path) -> Path:
    return binary.parent / f"{binary.name}{BACKUP_SUFFIX}"


def is_patched(binary: Path) -> bool:
    try:
        return PATCH_MARKER in binary.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def patch_selenium_manager(binary: Path | str) -> bool:
    target = Path(binary)
    if not target.is_file():
        return False
    if is_patched(target):
        return True

    bak = backup_path(target)
    if not bak.is_file():
        shutil.copy2(target, bak)
        os.chmod(bak, 0o755)

    script = WRAPPER_SCRIPT.format(
        patch_marker=PATCH_MARKER,
        binary_name=target.name,
        backup_suffix=BACKUP_SUFFIX,
        python=shutil.which("python3") or shutil.which("python") or "/usr/bin/python3",
    )

    target.write_text(script)
    os.chmod(target, 0o755)
    return True


def unpatch_selenium_manager(binary: Path | str) -> bool:
    target = Path(binary)
    bak = backup_path(target)
    if not bak.is_file():
        return False
    shutil.copy2(bak, target)
    os.chmod(target, 0o755)
    bak.unlink(missing_ok=True)
    return True


def patch_all_selenium_managers() -> list[Path]:
    patched: list[Path] = []
    for binary in _selenium_manager_candidates():
        try:
            if patch_selenium_manager(binary):
                patched.append(binary)
        except OSError:
            continue
    return patched


def unpatch_all_selenium_managers() -> list[Path]:
    unpatched: list[Path] = []
    for binary in _selenium_manager_candidates():
        if not is_patched(binary):
            continue
        try:
            if unpatch_selenium_manager(binary):
                unpatched.append(binary)
        except OSError:
            continue
    return unpatched