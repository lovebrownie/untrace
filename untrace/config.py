from __future__ import annotations

import json
from pathlib import Path

from untrace.injector import get_untrace_root


def config_path() -> Path:
    return get_untrace_root() / "config.json"


DEFAULT_CONFIG = {
    "js_injection": True,
    "chrome_flags": True,
    "chrome_wrapper": True,
    "chromedriver_patch": True,
}


def load() -> dict:
    path = config_path()
    if not path.is_file():
        return dict(DEFAULT_CONFIG)

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)

    config = dict(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return config

    if "js_injection" in data:
        config["js_injection"] = bool(data["js_injection"])
    if "chrome_flags" in data:
        config["chrome_flags"] = bool(data["chrome_flags"])
    if "chrome_wrapper" in data:
        config["chrome_wrapper"] = bool(data["chrome_wrapper"])
    if "chromedriver_patch" in data:
        config["chromedriver_patch"] = bool(data["chromedriver_patch"])
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
        "chrome_wrapper": bool(config.get("chrome_wrapper", True)),
        "chromedriver_patch": bool(config.get("chromedriver_patch", True)),
    }
    config_path().write_text(json.dumps(payload, indent=2) + "\n")


def resolve_install_features(
    *,
    stealth_extension: bool = False,
    launch_wrapper: bool = False,
    chromedriver_cdc: bool = False,
) -> dict:
    if not stealth_extension and not launch_wrapper and not chromedriver_cdc:
        return dict(DEFAULT_CONFIG)
    return {
        "js_injection": stealth_extension,
        "chrome_flags": launch_wrapper,
        "chrome_wrapper": launch_wrapper,
        "chromedriver_patch": chromedriver_cdc,
    }
