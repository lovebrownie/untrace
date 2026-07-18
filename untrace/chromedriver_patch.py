from __future__ import annotations

import os
import platform
import re
import shutil
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

if not IS_WINDOWS:
    import pwd
else:
    pwd = None  # type: ignore[assignment]

PATCH_MARKER = b"untrace chromedriver"
CDC_INJECTION_RE = re.compile(rb"\{window\.cdc.*?;\}")
BACKUP_SUFFIX = ".untrace.bak"

_BINARY_NOP = b" "

BINARY_STRING_PATCHES: tuple[tuple[bytes, bytes], ...] = (
    (b"enable-automation", _BINARY_NOP * len(b"enable-automation")),
    (b"test-type=webdriver", _BINARY_NOP * len(b"test-type=webdriver")),
)


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
    if sudo_user and pwd is not None:
        try:
            add(Path(pwd.getpwnam(sudo_user).pw_dir))
        except KeyError:
            add(Path(f"/home/{sudo_user}"))
    return homes


def _selenium_cache_roots() -> list[Path]:
    return [
        home / ".cache" / "selenium" / "chromedriver" for home in _home_dirs_to_search()
    ]


def backup_path(binary: Path) -> Path:
    return binary.parent / f"{binary.name}{BACKUP_SUFFIX}"


def find_chromedriver_binaries() -> list[Path]:
    names = ("chromedriver.exe", "chromedriver") if IS_WINDOWS else ("chromedriver",)
    search_roots: list[Path] = list(_selenium_cache_roots())
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
        if not os.access(resolved, os.X_OK):
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def is_patched(content: bytes) -> bool:
    return PATCH_MARKER in content


def _apply_binary_string_patches(content: bytes) -> bytes:
    updated = content
    for old, new in BINARY_STRING_PATCHES:
        if len(old) != len(new):
            raise ValueError(f"patch length mismatch: {old!r} vs {new!r}")
        if old not in updated:
            continue
        updated = updated.replace(old, new)
    return updated


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
            os.chmod(bak, 0o755)

        injection = match[0]
        replacement = b'{console.log("untrace chromedriver")}'.ljust(
            len(injection), b" "
        )
        if injection == replacement:
            return False

        updated = content.replace(injection, replacement, 1)
        updated = _apply_binary_string_patches(updated)
        handle.seek(0)
        handle.write(updated)
        handle.truncate()

    os.chmod(target, 0o755)
    return True


def unpatch_chromedriver_binary(path: Path | str) -> bool:
    target = Path(path)
    bak = backup_path(target)
    if not bak.is_file():
        return False
    if not target.is_file():
        shutil.copy2(bak, target)
        os.chmod(target, 0o755)
        bak.unlink(missing_ok=True)
        return True

    shutil.copy2(bak, target)
    os.chmod(target, 0o755)
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
