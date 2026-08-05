from __future__ import annotations

import shutil
import sysconfig
from pathlib import Path

from untrace.paths import (
    BACKUP_SUFFIX,
    IS_WINDOWS,
    LINUX_USER_UNTRACE_REL,
    backup_path_for,
    home_dirs_to_search,
)

PATCH_MARKER = "untrace selenium-manager"
WRAPPER_SCRIPT = """#!/bin/bash
# {patch_marker}
REAL="$(dirname "$(readlink -f "$0")")/{binary_name}{backup_suffix}"
USER_CHROME="${{HOME}}/{user_untrace}/chrome"
OUT="$("$REAL" "$@" 2>/dev/null)" || exit $?
if [ ! -f "$USER_CHROME" ]; then
  printf '%s\\n' "$OUT"
  exit 0
fi
{python} -c '
import json, sys
import subprocess
from pathlib import Path
data = json.load(sys.stdin)
result = data.get("result")
if isinstance(result, dict):
    if result.get("browser_path"):
        user = Path("~/{user_untrace}/chrome").expanduser()
        if user.is_file():
            result["browser_path"] = str(user)
    driver = result.get("driver_path")
    if driver:
        helper = Path("~/{user_untrace}/patch_driver.py").expanduser()
        if helper.is_file():
            subprocess.run([sys.executable, str(helper), str(driver)], capture_output=True)
print(json.dumps(data))
' <<< "$OUT"
"""


def _selenium_manager_candidates() -> list[Path]:
    candidates: list[Path] = []
    exe = sysconfig.get_config_var("EXE") or ""
    platform_dir = "windows" if IS_WINDOWS else "linux"

    for home in home_dirs_to_search():
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

        candidates.append(
            Path(sm.__file__).parent / platform_dir / f"selenium-manager{exe}"
        )
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
    return backup_path_for(binary)


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
        bak.chmod(0o755)

    script = WRAPPER_SCRIPT.format(
        patch_marker=PATCH_MARKER,
        binary_name=target.name,
        backup_suffix=BACKUP_SUFFIX,
        user_untrace=LINUX_USER_UNTRACE_REL,
        python=shutil.which("python3") or shutil.which("python") or "/usr/bin/python3",
    )

    target.write_text(script)
    target.chmod(0o755)
    return True


def unpatch_selenium_manager(binary: Path | str) -> bool:
    target = Path(binary)
    bak = backup_path(target)
    if not bak.is_file():
        return False
    shutil.copy2(bak, target)
    target.chmod(0o755)
    bak.unlink(missing_ok=True)
    return True


def patch_all_selenium_managers() -> list[Path]:
    if IS_WINDOWS:
        return []
    patched: list[Path] = []
    for binary in _selenium_manager_candidates():
        try:
            if patch_selenium_manager(binary):
                patched.append(binary)
        except OSError:
            continue
    return patched


def unpatch_all_selenium_managers() -> list[Path]:
    if IS_WINDOWS:
        return []
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


def any_patched() -> bool:
    for binary in _selenium_manager_candidates():
        if is_patched(binary):
            return True
    return False
