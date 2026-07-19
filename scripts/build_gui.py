from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICON = ASSETS / "icon.ico"
ENTRY = ROOT / "untrace" / "gui_windows.py"


def main() -> int:
    if not ICON.is_file():
        print(f"missing icon: {ICON}", file=sys.stderr)
        return 1
    if not ENTRY.is_file():
        print(f"missing entry: {ENTRY}", file=sys.stderr)
        return 1
    return subprocess.call(
        [
            "pyinstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onefile",
            "--uac-admin",
            "--name",
            "Untrace",
            "--icon",
            str(ICON),
            "--paths",
            str(ROOT),
            "--collect-all",
            "untrace",
            "--add-data",
            f"{ASSETS}{os.pathsep}assets",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build" / "pyinstaller"),
            "--specpath",
            str(ROOT / "build" / "pyinstaller"),
            str(ENTRY),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
