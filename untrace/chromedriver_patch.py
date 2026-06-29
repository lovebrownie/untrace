from __future__ import annotations

import os
import re
from pathlib import Path

PATCH_MARKER = b"untrace chromedriver"
CDC_INJECTION_RE = re.compile(rb"\{window\.cdc.*?;\}")


def find_chromedriver_binaries() -> list[Path]:
    candidates: list[Path] = []
    for base in (
        Path.home() / ".cache" / "selenium" / "chromedriver",
        Path("/usr/local/bin"),
        Path("/usr/bin"),
    ):
        if not base.is_dir():
            continue
        if base.name == "chromedriver" and base.is_file():
            candidates.append(base)
            continue
        candidates.extend(p for p in base.rglob("chromedriver") if p.is_file())

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

        injection = match[0]
        replacement = b'{console.log("untrace chromedriver")}'.ljust(
            len(injection), b" "
        )
        if injection == replacement:
            return False

        updated = content.replace(injection, replacement, 1)
        handle.seek(0)
        handle.write(updated)
        handle.truncate()

    os.chmod(target, 0o755)
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
