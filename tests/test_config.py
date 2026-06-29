import pytest

from untrace import config, injector
from untrace.__main__ import CHROME_FLAGS, DEFAULT_CHROME_FLAGS, build_chrome_wrapper_script, chrome_launch_flags


@pytest.mark.parametrize(
    ("stealth", "flags", "expected"),
    [
        (False, False, config.DEFAULT_CONFIG),
        (True, True, {"js_injection": True, "chrome_flags": True}),
        (False, True, {"js_injection": False, "chrome_flags": True}),
        (True, False, {"js_injection": True, "chrome_flags": True}),
    ],
)
def test_resolve_install_features(stealth, flags, expected):
    assert config.resolve_install_features(stealth=stealth, flags=flags) == expected


def test_chrome_launch_flags_respect_config(monkeypatch, tmp_path):
    injector.use_untrace_root(tmp_path / "untrace")
    monkeypatch.setattr(injector, "is_installed", lambda: True)
    try:
        config.save({"js_injection": False, "chrome_flags": True})
        flags = chrome_launch_flags()
        assert all(CHROME_FLAGS[name] in flags for name in DEFAULT_CHROME_FLAGS)

        config.save({"js_injection": True, "chrome_flags": False})
        assert chrome_launch_flags() == []
    finally:
        injector.clear_untrace_root_override()


def test_chrome_wrapper_seeds_extension_for_selenium():
    flags = [CHROME_FLAGS[name] for name in DEFAULT_CHROME_FLAGS]
    patch = build_chrome_wrapper_script(flags)

    assert "UNTRACE_AUTOMATION" in patch
    assert "_resolve_untrace_root" in patch
    assert "_seed_untrace_extension" in patch
    assert 'if [ "$UNTRACE_AUTOMATION" = "1" ]; then' in patch
    assert "--enable-automation" in patch
    assert "--disable-background-networking" in patch
    assert "AutomationModeDesktop,AutomationModeAndroid" in patch
    assert "AutomationControlled" not in patch.split("exec ")[-1]
    assert "--disable-blink-features=*" in patch
    assert "--disable-blink-features)" in patch
    assert "--window-size=1920,1080" in patch
    assert "_untrace_wants_headless" in patch
    assert "_untrace_runner" in patch
    assert '_untrace_filtered+=("$arg")' in patch