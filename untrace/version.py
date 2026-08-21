from __future__ import annotations

import platform
import sys
from functools import lru_cache
from pathlib import Path

from untrace.paths import IS_WINDOWS


def _repo_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _pyproject_path() -> Path:
    return _repo_root() / "pyproject.toml"


@lru_cache(maxsize=1)
def read_project() -> dict:
    path = _pyproject_path()
    if not path.is_file():
        raise FileNotFoundError(f"pyproject.toml not found: {path}")
    import tomllib

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"missing [project] in {path}")
    return dict(project)


def read_version() -> str:
    version = read_project().get("version")
    if not version:
        raise ValueError(f"missing [project].version in {_pyproject_path()}")
    return str(version).strip()


def _primary_author() -> dict:
    authors = read_project().get("authors") or []
    if not authors or not isinstance(authors[0], dict):
        raise ValueError(f"missing [project].authors in {_pyproject_path()}")
    return authors[0]


def author_name() -> str:
    name = str(_primary_author().get("name") or "").strip()
    if not name:
        raise ValueError(f"missing author name in {_pyproject_path()}")
    return name


def author_email() -> str:
    email = str(_primary_author().get("email") or "").strip()
    if not email:
        raise ValueError(f"missing author email in {_pyproject_path()}")
    return email


def author_contact() -> str:
    return f"{author_name()} <{author_email()}>"


__version__ = read_version()


def version_tag(version: str | None = None) -> str:
    ver = (version or __version__).lstrip("vV")
    return f"v{ver}"


def gui_exe_name(version: str | None = None) -> str:
    return f"Untrace-{version_tag(version)}-Portable"


def gui_artifact_name(version: str | None = None) -> str:
    if IS_WINDOWS:
        return f"Untrace-{version_tag(version)}-Setup.exe"
    ver = (version or __version__).lstrip("vV")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
    return f"untrace_{ver}_{arch}.deb"


def extension_zip_name(version: str | None = None) -> str:
    return f"extension-{version_tag(version)}.zip"


def windows_zip_name(version: str | None = None) -> str:
    return f"Untrace-{version_tag(version)}-Windows.zip"
