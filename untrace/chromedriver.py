from __future__ import annotations

import shutil
import stat
from pathlib import Path

from undetected.cdc import (
    CDC_INJECTION_RE,
    blank_substrings,
    cdc_console_replacement,
    default_string_blanks,
)
from untrace.paths import IS_WINDOWS, backup_path_for, home_dirs_to_search

PATCH_MARKER = b"untrace chromedriver"

BINARY_STRING_PATCHES: tuple[tuple[bytes, bytes], ...] = tuple(
    (needle, b" " * len(needle)) for needle in default_string_blanks(windows=IS_WINDOWS)
)


def _driver_search_roots() -> list[Path]:
    roots: list[Path] = []
    for home in home_dirs_to_search():
        roots.append(home / ".cache" / "selenium" / "chromedriver")
        # webdriver-manager (Python) default cache.
        roots.append(home / ".wdm")
    return roots


def backup_path(binary: Path) -> Path:
    return backup_path_for(binary)


def find_chromedriver_binaries() -> list[Path]:
    names = ("chromedriver.exe", "chromedriver") if IS_WINDOWS else ("chromedriver",)
    search_roots: list[Path] = _driver_search_roots()
    if not IS_WINDOWS:
        search_roots.extend((Path("/usr/local/bin"), Path("/usr/bin")))

    candidates: list[Path] = []
    for base in search_roots:
        if not base.is_dir():
            continue
        if base.name in names and base.is_file():
            candidates.append(base)
            continue
        for name in names:
            candidates.extend(p for p in base.rglob(name) if p.is_file())

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        try:
            mode = resolved.stat().st_mode
        except OSError:
            continue
        # Windows does not track POSIX execute bits; any file there is a candidate.
        if not IS_WINDOWS and not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def is_patched(content: bytes) -> bool:
    return PATCH_MARKER in content


def _apply_binary_string_patches(content: bytes) -> bytes:
    return blank_substrings(content, (old for old, _ in BINARY_STRING_PATCHES))


def patch_chromedriver_binary(path: Path | str) -> bool:
    target = Path(path)
    if not target.is_file():
        return False

    with target.open("r+b") as handle:
        content = handle.read()
        if is_patched(content):
            return True

        match = CDC_INJECTION_RE.search(content)
        if not match:
            return False

        bak = backup_path(target)
        if not bak.is_file():
            shutil.copy2(target, bak)
            bak.chmod(0o755)

        injection = match[0]
        replacement = cdc_console_replacement(injection, PATCH_MARKER)
        if injection == replacement:
            return False

        updated = content.replace(injection, replacement, 1)
        updated = _apply_binary_string_patches(updated)
        handle.seek(0)
        handle.write(updated)
        handle.truncate()

    target.chmod(0o755)
    return True


def unpatch_chromedriver_binary(path: Path | str) -> bool:
    target = Path(path)
    bak = backup_path(target)
    if not bak.is_file():
        return False
    if not target.is_file():
        shutil.copy2(bak, target)
        target.chmod(0o755)
        bak.unlink(missing_ok=True)
        return True

    shutil.copy2(bak, target)
    target.chmod(0o755)
    bak.unlink(missing_ok=True)
    return True


def patch_all_chromedrivers() -> list[Path]:
    patched: list[Path] = []
    for binary in find_chromedriver_binaries():
        try:
            if patch_chromedriver_binary(binary):
                patched.append(binary)
        except OSError:
            continue
    return patched


def unpatch_all_chromedrivers() -> list[Path]:
    unpatched: list[Path] = []
    for binary in find_chromedriver_binaries():
        try:
            content = binary.read_bytes()
        except OSError:
            continue
        if not is_patched(content):
            continue
        try:
            if unpatch_chromedriver_binary(binary):
                unpatched.append(binary)
        except OSError:
            continue
    return unpatched
