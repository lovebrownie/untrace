from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from untrace.paths import (
    IS_WINDOWS,
    chown_to_invoker,
    linux_invoking_pw,
    user_untrace_root,
)

_file = None
_enabled = False

LOG_NAME = "untrace.log"


def log_dir() -> Path:
    path = user_untrace_root()
    if not path.parts:
        rel = (
            Path("AppData") / "Local" / "Untrace"
            if IS_WINDOWS
            else Path(".local") / "share" / "untrace"
        )
        path = Path.home() / rel
    path.mkdir(parents=True, exist_ok=True)
    chown_to_invoker(path)
    return path


def log_path() -> Path:
    return log_dir() / LOG_NAME


def display_log_path() -> str:
    if IS_WINDOWS:
        return r"%LOCALAPPDATA%\Untrace\untrace.log"
    return "~/.local/share/untrace/untrace.log"


def _linux_user_session_env(pw) -> dict[str, str]:
    env = os.environ.copy()
    runtime = f"/run/user/{pw.pw_uid}"
    env["HOME"] = pw.pw_dir
    env["USER"] = pw.pw_name
    env["LOGNAME"] = pw.pw_name
    env["XDG_RUNTIME_DIR"] = runtime
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"
    env.pop("SUDO_USER", None)
    env.pop("SUDO_UID", None)
    env.pop("SUDO_GID", None)
    env.pop("PKEXEC_UID", None)
    return env


def _linux_run_as_invoker(argv: list[str]) -> None:
    pw = linux_invoking_pw()
    env = _linux_user_session_env(pw) if pw is not None else os.environ.copy()
    preexec = None
    if (
        pw is not None
        and hasattr(os, "geteuid")
        and os.geteuid() == 0
        and pw.pw_uid != 0
    ):
        uid, gid = pw.pw_uid, pw.pw_gid

        def preexec() -> None:
            os.setgid(gid)
            os.setuid(uid)

    subprocess.Popen(
        argv,
        env=env,
        preexec_fn=preexec,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def reveal_in_file_manager() -> Path:
    path = log_path()
    if not path.is_file():
        path.write_text("", encoding="utf-8")
        chown_to_invoker(path)
    resolved = path.resolve()
    if IS_WINDOWS:
        subprocess.Popen(
            ["explorer", f"/select,{resolved}"],
            start_new_session=True,
        )
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(resolved)], start_new_session=True)
    else:
        # GUI runs elevated; Nautilus refuses root — always reveal as the invoker.
        if shutil.which("nautilus"):
            _linux_run_as_invoker(["nautilus", "--select", str(resolved)])
        elif shutil.which("dbus-send"):
            uri = resolved.as_uri()
            _linux_run_as_invoker(
                [
                    "dbus-send",
                    "--session",
                    "--dest=org.freedesktop.FileManager1",
                    "--type=method_call",
                    "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:{uri}",
                    "string:",
                ]
            )
        else:
            _linux_run_as_invoker(["xdg-open", str(resolved.parent)])
    return path


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
            write(f"[untrace] {command}")
        return path

    _file = path.open("a", encoding="utf-8", errors="replace")
    chown_to_invoker(path)
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
    global _file
    if _enabled and _file is not None:
        try:
            _file.write(line)
            _file.flush()
        except OSError:
            pass
        return
    try:
        path = log_path()
        with path.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(line)
        chown_to_invoker(path)
    except OSError:
        pass


def close() -> None:
    global _file, _enabled
    if _file is not None:
        try:
            _file.flush()
            _file.close()
        except OSError:
            pass
    _file = None
    _enabled = False
    if sys.stdout is not sys.__stdout__:
        sys.stdout = sys.__stdout__
    if sys.stderr is not sys.__stderr__:
        sys.stderr = sys.__stderr__
