import pytest

from untrace import config, injector
from untrace.__main__ import (
    CHROME_FLAGS,
    DEFAULT_CHROME_FLAGS,
    LAUNCH_FLAGS_FILE,
    build_chrome_wrapper_script,
    chrome_launch_flags,
    write_launch_flags,
)


@pytest.mark.parametrize(
    ("stealth", "flags", "chromedriver", "expected"),
    [
        (False, False, False, config.DEFAULT_CONFIG),
        (
            True,
            True,
            True,
            {
                "js_injection": True,
                "chrome_flags": True,
                "chrome_wrapper": True,
                "chromedriver_patch": True,
            },
        ),
        (
            False,
            True,
            False,
            {
                "js_injection": False,
                "chrome_flags": True,
                "chrome_wrapper": True,
                "chromedriver_patch": False,
            },
        ),
        (
            True,
            False,
            False,
            {
                "js_injection": True,
                "chrome_flags": False,
                "chrome_wrapper": False,
                "chromedriver_patch": False,
            },
        ),
        (
            False,
            False,
            True,
            {
                "js_injection": False,
                "chrome_flags": False,
                "chrome_wrapper": False,
                "chromedriver_patch": True,
            },
        ),
    ],
)
def test_resolve_install_features(stealth, flags, chromedriver, expected):
    assert (
        config.resolve_install_features(
            stealth=stealth, flags=flags, chromedriver=chromedriver
        )
        == expected
    )


def test_chrome_launch_flags_respect_config(monkeypatch, tmp_path):
    injector.use_untrace_root(tmp_path / "untrace")
    monkeypatch.setattr(injector, "is_installed", lambda: True)
    monkeypatch.setattr(
        injector, "extension_launch_flags", lambda: ["--load-extension=/tmp/ext"]
    )
    try:
        config.save({"js_injection": False, "chrome_flags": True})
        flags = chrome_launch_flags()
        assert all(CHROME_FLAGS[name] in flags for name in DEFAULT_CHROME_FLAGS)
        assert "--load-extension=/tmp/ext" not in flags

        config.save({"js_injection": True, "chrome_flags": False})
        assert chrome_launch_flags() == ["--load-extension=/tmp/ext"]
    finally:
        injector.clear_untrace_root_override()


def test_chrome_wrapper_uses_random_profile_only_when_enabled():
    flags = [CHROME_FLAGS[name] for name in DEFAULT_CHROME_FLAGS]
    random_on = build_chrome_wrapper_script(flags, random_profile=True)
    random_off = build_chrome_wrapper_script(flags, random_profile=False)

    assert "chrome_random_profiles" in random_on
    assert "chrome_random_profiles" not in random_off
    assert ".config/google-chrome" in random_off


def test_chrome_wrapper_seeds_extension_for_selenium():
    flags = [CHROME_FLAGS[name] for name in DEFAULT_CHROME_FLAGS]
    patch = build_chrome_wrapper_script(flags, random_profile=True)

    assert "UNTRACE_AUTOMATION" in patch
    assert "_resolve_untrace_root" in patch
    assert "_seed_untrace_extension" in patch
    assert 'if [ "$UNTRACE_AUTOMATION" = "1" ]; then' in patch
    assert "--enable-automation" in patch
    assert "--disable-background-networking" in patch
    assert "_read_launch_flags" in patch
    assert "launch.flags" in patch
    assert "${_untrace_launch_flags[@]}" in patch
    assert "AutomationControlled" not in patch
    assert "--disable-blink-features=AutomationControlled" not in patch
    assert "--disable-blink-features=*" in patch
    assert "--disable-blink-features)" in patch
    assert "--window-size=1920,1080" in patch
    assert "_untrace_wants_headless" in patch
    assert "_untrace_runner" in patch
    assert '_untrace_filtered+=("$arg")' in patch


def test_write_launch_flags_persists_flags(tmp_path):
    flags = [CHROME_FLAGS[name] for name in DEFAULT_CHROME_FLAGS]
    path = write_launch_flags(flags, tmp_path)
    assert path.name == LAUNCH_FLAGS_FILE
    saved = path.read_text().splitlines()
    assert all(flag in saved for flag in flags)
    assert "AutomationControlled" in path.read_text()
