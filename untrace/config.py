from __future__ import annotations

import json
from pathlib import Path

from untrace.injector import get_untrace_root


def config_path() -> Path:
    return get_untrace_root() / "config.json"


DEFAULT_CONFIG = {
    "js_injection": True,
    "chrome_flags": True,
}


def load() -> dict:
    path = config_path()
    if not path.is_file():
        return dict(DEFAULT_CONFIG)

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError, OSError:
        return dict(DEFAULT_CONFIG)

    config = dict(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return config

    if "js_injection" in data:
        config["js_injection"] = bool(data["js_injection"])
    if "chrome_flags" in data:
        config["chrome_flags"] = bool(data["chrome_flags"])
    return config


def clear() -> None:
    path = config_path()
    if path.is_file():
        path.unlink()


def save(config: dict) -> None:
    root = get_untrace_root()
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "js_injection": bool(config.get("js_injection", True)),
        "chrome_flags": bool(config.get("chrome_flags", True)),
    }
    config_path().write_text(json.dumps(payload, indent=2) + "\n")


def resolve_install_features(*, stealth: bool = False, flags: bool = False) -> dict:
    if stealth and flags:
        return {"js_injection": True, "chrome_flags": True}
    if flags:
        return {"js_injection": False, "chrome_flags": True}
    if stealth:
        return {"js_injection": True, "chrome_flags": True}
    return dict(DEFAULT_CONFIG)
