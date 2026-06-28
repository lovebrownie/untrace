import pytest

from untrace import config, injector
from untrace.__main__ import CHROME_FLAGS, DEFAULT_CHROME_FLAGS, build_chrome_wrapper_script, chrome_launch_flags


@pytest.mark.parametrize(
    ("stealth", "flags", "expected"),
    [
        (False, False, config.DEFAULT_CONFIG),
        (True, True, {"js_injection": True, "chrome_flags": True}),
        (False, True, {"js_injection": False, "chrome_flags": True}),
        (True, False, {"js_injection": True, "chrome_flags": False}),
    ],
)
def test_resolve_install_features(stealth, flags, expected):
    assert config.resolve_install_features(stealth=stealth, flags=flags) == expected


def test_chrome_launch_flags_respect_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(injector, "is_installed", lambda: True)

    config.save({"js_injection": False, "chrome_flags": True})
    flags = chrome_launch_flags()
    assert all(CHROME_FLAGS[name] in flags for name in DEFAULT_CHROME_FLAGS)

    config.save({"js_injection": True, "chrome_flags": False})
    assert chrome_launch_flags() == []


def test_chrome_wrapper_seeds_extension_for_selenium():
    patch = build_chrome_wrapper_script(["--start-maximized"])

    assert "UNTRACE_AUTOMATION" in patch
    assert "seed_profile.py" in patch
    assert "_seed_untrace_extension" in patch
    assert 'if [ "$UNTRACE_AUTOMATION" = "1" ]; then' in patch