from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICON = ASSETS / "icon.ico"
PYPROJECT = ROOT / "pyproject.toml"
ENTRY = ROOT / "untrace" / "gui_windows.py"
DIST = ROOT / "dist"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from untrace.version import __version__, extension_zip_name, gui_exe_name


def pack_extension(*, output: str | None = None, version: str | None = None) -> Path:
    from untrace.__main__ import pack_extension as _pack

    return _pack(output=output, version=version)


def build_gui(*, version: str | None = None) -> int:
    if not PYPROJECT.is_file():
        print(f"missing pyproject.toml: {PYPROJECT}", file=sys.stderr)
        return 1
    if not ICON.is_file():
        print(f"missing icon: {ICON}", file=sys.stderr)
        return 1
    if not ENTRY.is_file():
        print(f"missing entry: {ENTRY}", file=sys.stderr)
        return 1
    DIST.mkdir(parents=True, exist_ok=True)
    ver = version or __version__
    name = gui_exe_name(ver)
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        name,
        "--icon",
        str(ICON),
        "--paths",
        str(ROOT),
        "--collect-all",
        "untrace",
        "--add-data",
        f"{ASSETS}{os.pathsep}assets",
        "--add-data",
        f"{PYPROJECT}{os.pathsep}.",
        "--distpath",
        str(DIST),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build" / "pyinstaller"),
    ]
    if sys.platform == "win32":
        cmd.append("--uac-admin")
    cmd.append(str(ENTRY))
    return subprocess.call(cmd)


def build_all(*, output: str | None = None, version: str | None = None) -> int:
    code = build_gui(version=version)
    if code != 0:
        return code
    pack_extension(output=output, version=version)
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build Untrace dist artifacts")
    parser.add_argument(
        "--gui-only",
        action="store_true",
        help=f"build {gui_exe_name()} binary only",
    )
    parser.add_argument(
        "--extension-only",
        action="store_true",
        help=f"pack {extension_zip_name()} only",
    )
    parser.add_argument("--output", metavar="PATH", help="extension zip path")
    parser.add_argument("--version", metavar="VER", help="artifact / manifest version")
    args = parser.parse_args(argv)

    if args.gui_only and args.extension_only:
        parser.error("use only one of --gui-only / --extension-only")
    if args.gui_only:
        return build_gui(version=args.version)
    if args.extension_only:
        pack_extension(output=args.output, version=args.version)
        return 0
    return build_all(output=args.output, version=args.version)


if __name__ == "__main__":
    raise SystemExit(main())
