from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICON = ASSETS / "icon.ico"
ICON_PNG = ASSETS / "icon.png"
PYPROJECT = ROOT / "pyproject.toml"
ENTRY_MAIN = ROOT / "untrace" / "__main__.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from untrace.version import (
    __version__,
    extension_zip_name,
    gui_artifact_name,
)


def pack_extension(*, output: str | None = None, version: str | None = None) -> Path:
    from untrace.__main__ import pack_extension as _pack

    return _pack(output=output, version=version)


def _linux_deb_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise RuntimeError(f"unsupported deb arch: {machine}")


def _read_project_meta() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return dict(data.get("project") or {})


def _deb_maintainer(meta: dict) -> str:
    authors = meta.get("authors") or []
    if authors and isinstance(authors[0], dict):
        name = str(authors[0].get("name") or "carlos").strip()
        email = str(authors[0].get("email") or "").strip()
        if email:
            return f"{name} <{email}>"
        return f"{name} <carlos@users.noreply.github.com>"
    return "carlos <carlos@users.noreply.github.com>"


def _pack_linux_deb(binary: Path, *, version: str) -> Path:
    if not binary.is_file():
        raise FileNotFoundError(binary)
    png_src = ICON_PNG if ICON_PNG.is_file() else ASSETS / "icon-128.png"
    if not png_src.is_file():
        raise FileNotFoundError(png_src)
    if shutil.which("dpkg-deb") is None:
        raise RuntimeError("dpkg-deb not found (install dpkg)")

    meta = _read_project_meta()
    ver = version.lstrip("vV")
    arch = _linux_deb_arch()
    pkg_name = f"untrace_{ver}_{arch}"
    root = BUILD / "deb" / pkg_name
    if root.exists():
        shutil.rmtree(root)

    deb_dir = root / "DEBIAN"
    lib_dir = root / "usr" / "lib" / "untrace"
    bin_dir = root / "usr" / "bin"
    apps_dir = root / "usr" / "share" / "applications"
    doc_dir = root / "usr" / "share" / "doc" / "untrace"
    for path in (deb_dir, lib_dir, bin_dir, apps_dir, doc_dir):
        path.mkdir(parents=True)

    app_bin = lib_dir / "untrace"
    shutil.copy2(binary, app_bin)
    app_bin.chmod(app_bin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    wrapper = bin_dir / "untrace"
    wrapper.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'exec /usr/lib/untrace/untrace "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    (apps_dir / "untrace.desktop").write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Untrace",
                "Comment=Untrace install manager",
                "Exec=untrace --gui",
                "Icon=untrace",
                "Terminal=false",
                "Categories=Utility;",
                "StartupWMClass=Untrace",
                "",
            ]
        ),
        encoding="utf-8",
    )

    for size_name, src_name in (
        ("128x128", "icon-128.png"),
        ("48x48", "icon-48.png"),
        ("16x16", "icon-16.png"),
    ):
        src = ASSETS / src_name
        if not src.is_file():
            src = png_src if size_name == "128x128" else None
        if src is None or not src.is_file():
            continue
        icon_dir = root / "usr" / "share" / "icons" / "hicolor" / size_name / "apps"
        icon_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, icon_dir / "untrace.png")

    maintainer = _deb_maintainer(meta)
    license_id = str(meta.get("license") or "MIT")
    summary = str(
        meta.get("description") or "Untrace Chrome stealth install manager"
    ).strip()
    homepage = ""
    urls = meta.get("urls") if isinstance(meta.get("urls"), dict) else {}
    if urls:
        homepage = str(urls.get("Homepage") or urls.get("Repository") or "").strip()

    control_lines = [
        "Package: untrace",
        f"Version: {ver}",
        "Section: utils",
        "Priority: optional",
        f"Architecture: {arch}",
        f"Maintainer: {maintainer}",
        f"Homepage: {homepage}" if homepage else None,
        "Depends: libtk8.6 | libtk",
        f"Description: {summary}",
        " Untrace makes Chrome automation harder to detect. This package installs",
        " the Untrace GUI and CLI (untrace on PATH), with a desktop launcher.",
        " Use the GUI or `untrace --install` to enable stealth, flags, and",
        " chromedriver patches on the local machine.",
        "",
    ]
    (deb_dir / "control").write_text(
        "\n".join(line for line in control_lines if line is not None),
        encoding="utf-8",
    )

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    (doc_dir / "copyright").write_text(
        "\n".join(
            [
                "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/",
                "Upstream-Name: untrace",
                f"Upstream-Contact: {maintainer}",
                f"Source: {homepage}" if homepage else "Source: local",
                "",
                "Files: *",
                "Copyright: 2026 carlos",
                f"License: {license_id}",
                "",
                f"License: {license_id}",
                *[f" {line}" if line else " ." for line in license_text.splitlines()],
                "",
            ]
        ),
        encoding="utf-8",
    )

    changelog = doc_dir / "changelog.Debian"
    stamp = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    changelog.write_text(
        "\n".join(
            [
                f"untrace ({ver}) unstable; urgency=medium",
                "",
                f"  * Release {ver}",
                "",
                f" -- {maintainer}  {stamp}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.check_call(["gzip", "-fn9", str(changelog)])

    readme = ROOT / "README.md"
    if readme.is_file():
        shutil.copy2(readme, doc_dir / "README.md")

    postinst = deb_dir / "postinst"
    postinst.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -e",
                "if command -v update-desktop-database >/dev/null 2>&1; then",
                "  update-desktop-database -q /usr/share/applications || true",
                "fi",
                "if command -v gtk-update-icon-cache >/dev/null 2>&1; then",
                "  gtk-update-icon-cache -f -t -q /usr/share/icons/hicolor || true",
                "fi",
                "",
            ]
        ),
        encoding="utf-8",
    )
    postinst.chmod(postinst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    out = DIST / f"untrace_{ver}_{arch}.deb"
    if out.exists():
        out.unlink()
    code = subprocess.call(
        ["dpkg-deb", "--root-owner-group", "--build", str(root), str(out)]
    )
    if code != 0:
        raise RuntimeError(f"dpkg-deb failed with code {code}")
    print(f"deb: {out}")
    print("install with: sudo apt install ./dist/" + out.name)
    return out


def _find_iscc() -> Path | None:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return Path(found)
    for candidate in (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Inno Setup 6"
        / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Inno Setup 6"
        / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "Inno Setup 6"
        / "ISCC.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def _pack_windows_setup(binary: Path, *, version: str) -> Path:
    if not binary.is_file():
        raise FileNotFoundError(binary)
    iscc = _find_iscc()
    if iscc is None:
        raise RuntimeError(
            "Inno Setup compiler (ISCC.exe) not found. "
            "Install from https://jrsoftware.org/isinfo.php or: choco install innosetup"
        )

    ver = version.lstrip("vV")
    iss = ROOT / "scripts" / "windows" / "untrace.iss"
    if not iss.is_file():
        raise FileNotFoundError(iss)

    DIST.mkdir(parents=True, exist_ok=True)
    out_name = f"Untrace-v{ver}-Setup.exe"
    out = DIST / out_name
    if out.exists():
        out.unlink()

    cmd = [
        str(iscc),
        f"/DMyAppVersion={ver}",
        f"/DSourceExe={binary.resolve()}",
        f"/DRepoRoot={ROOT.resolve()}",
        f"/DOutputDir={DIST.resolve()}",
        str(iss.resolve()),
    ]
    code = subprocess.call(cmd)
    if code != 0:
        raise RuntimeError(f"ISCC failed with code {code}")
    if not out.is_file():
        raise FileNotFoundError(f"missing setup output: {out}")
    print(f"setup: {out}")
    print(f"install with: {out.name}")
    return out


def build_gui(*, version: str | None = None) -> int:
    if not PYPROJECT.is_file():
        print(f"missing pyproject.toml: {PYPROJECT}", file=sys.stderr)
        return 1
    if not ICON.is_file():
        print(f"missing icon: {ICON}", file=sys.stderr)
        return 1
    entry = ENTRY_MAIN
    if not entry.is_file():
        print(f"missing entry: {entry}", file=sys.stderr)
        return 1
    DIST.mkdir(parents=True, exist_ok=True)
    ver = version or __version__
    icon_arg = str(ICON)
    pyinstaller_dist = BUILD / "pyinstaller" / "dist"
    pyinstaller_dist.mkdir(parents=True, exist_ok=True)
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--console",
        "--onefile",
        "--name",
        "untrace",
        "--icon",
        icon_arg,
        "--paths",
        str(ROOT),
        "--collect-all",
        "untrace",
        "--add-data",
        f"{ASSETS}{os.pathsep}assets",
        "--add-data",
        f"{PYPROJECT}{os.pathsep}.",
        "--distpath",
        str(pyinstaller_dist),
        "--workpath",
        str(BUILD / "pyinstaller" / "work"),
        "--specpath",
        str(BUILD / "pyinstaller"),
    ]
    if sys.platform == "win32":
        cmd.append("--uac-admin")
    cmd.append(str(entry))
    code = subprocess.call(cmd)
    if code != 0:
        return code

    binary_name = "untrace.exe" if sys.platform == "win32" else "untrace"
    binary = pyinstaller_dist / binary_name
    if not binary.is_file():
        print(f"missing pyinstaller binary: {binary}", file=sys.stderr)
        return 1

    try:
        if sys.platform == "win32":
            _pack_windows_setup(binary, version=ver)
        else:
            _pack_linux_deb(binary, version=ver)
    except Exception as exc:
        kind = "setup" if sys.platform == "win32" else "deb"
        print(f"{kind} pack failed: {exc}", file=sys.stderr)
        return 1
    return 0


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
        help=f"build {gui_artifact_name()} only",
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
