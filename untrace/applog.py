from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

_file = None
_enabled = False


def _user_home() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE") or Path.home())
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and os.geteuid() == 0:
        try:
            import pwd

            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except (KeyError, ImportError):
            pass
    return Path.home()


def log_dir() -> Path:
    path = _user_home() / "Documents" / "Untrace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return log_dir() / "untrace.log"


class _Tee:
    def __init__(self, stream, file) -> None:
        self._stream = stream
        self._file = file

    def write(self, data: str) -> int:
        if self._stream is not None:
            try:
                self._stream.write(data)
            except OSError:
                pass
        try:
            self._file.write(data)
            self._file.flush()
        except OSError:
            pass
        return len(data)

    def flush(self) -> None:
        if self._stream is not None:
            try:
                self._stream.flush()
            except OSError:
                pass
        try:
            self._file.flush()
        except OSError:
            pass

    def fileno(self) -> int:
        if self._stream is not None and hasattr(self._stream, "fileno"):
            return self._stream.fileno()
        raise OSError("no fileno")

    def isatty(self) -> bool:
        return bool(
            self._stream is not None
            and getattr(self._stream, "isatty", lambda: False)()
        )


def enable(command: str | None = None) -> Path:
    global _file, _enabled
    path = log_path()
    if _enabled:
        if command:
            print(f"[untrace] {command}")
        return path

    _file = open(path, "a", encoding="utf-8", errors="replace")
    stamp = datetime.now().isoformat(timespec="seconds")
    _file.write(f"\n--- {stamp} ---\n")
    if command:
        _file.write(f"command: {command}\n")
    _file.flush()

    sys.stdout = _Tee(sys.__stdout__, _file)
    sys.stderr = _Tee(sys.__stderr__, _file)
    _enabled = True
    return path


def write(message: str) -> None:
    line = message if message.endswith("\n") else message + "\n"
    if _enabled:
        print(line, end="")
        return
    try:
        with open(log_path(), "a", encoding="utf-8", errors="replace") as fh:
            fh.write(line)
    except OSError:
        pass
