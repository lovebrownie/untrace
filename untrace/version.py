from __future__ import annotations

import platform
import sys
from pathlib import Path


def _repo_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _pyproject_path() -> Path:
    return _repo_root() / "pyproject.toml"


def read_version() -> str:
    path = _pyproject_path()
    if not path.is_file():
        raise FileNotFoundError(f"pyproject.toml not found: {path}")
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not version:
        raise ValueError(f"missing [project].version in {path}")
    return str(version).strip()


__version__ = read_version()


def version_tag(version: str | None = None) -> str:
    ver = (version or __version__).lstrip("vV")
    return f"v{ver}"


def gui_exe_name(version: str | None = None) -> str:
    return f"Untrace-{version_tag(version)}"


def gui_artifact_name(version: str | None = None) -> str:
    if sys.platform == "win32":
        return f"Untrace-{version_tag(version)}-Setup.exe"
    ver = (version or __version__).lstrip("vV")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
    return f"untrace_{ver}_{arch}.deb"


def extension_zip_name(version: str | None = None) -> str:
    return f"untrace-injector-{version_tag(version)}.zip"
