from __future__ import annotations

import json

from untrace.injector import UNTRACE_ROOT

CONFIG_PATH = UNTRACE_ROOT / "config.json"

DEFAULT_CONFIG = {
    "js_injection": True,
    "chrome_flags": True,
}


def load() -> dict:
    if not CONFIG_PATH.is_file():
        return dict(DEFAULT_CONFIG)

    try:
        data = json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
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
    if CONFIG_PATH.is_file():
        CONFIG_PATH.unlink()


def save(config: dict) -> None:
    UNTRACE_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "js_injection": bool(config.get("js_injection", True)),
        "chrome_flags": bool(config.get("chrome_flags", True)),
    }
    CONFIG_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def resolve_install_features(*, stealth: bool = False, flags: bool = False) -> dict:
    if stealth and flags:
        return {"js_injection": True, "chrome_flags": True}
    if flags:
        return {"js_injection": False, "chrome_flags": True}
    if stealth:
        return {"js_injection": True, "chrome_flags": False}
    return dict(DEFAULT_CONFIG)