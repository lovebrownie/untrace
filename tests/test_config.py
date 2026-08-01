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


def test_chrome_launch_flags_respect_config(tmp_path):
    injector.use_untrace_root(tmp_path / "untrace")
    try:
        config.save({"js_injection": False, "chrome_flags": True})
        flags = chrome_launch_flags()
        assert all(CHROME_FLAGS[name] in flags for name in DEFAULT_CHROME_FLAGS)

        config.save({"js_injection": True, "chrome_flags": False})
        assert chrome_launch_flags() == []
    finally:
        injector.clear_untrace_root_override()


def test_chrome_wrapper_script():
    random_on = build_chrome_wrapper_script(random_profile=True)
    random_off = build_chrome_wrapper_script(random_profile=False)

    assert "chrome_random_profiles" in random_on
    assert "chrome_random_profiles" not in random_off
    assert ".config/google-chrome" in random_off

    assert "UNTRACE_AUTOMATION" in random_on
    assert "_resolve_untrace_root" in random_on
    assert "_seed_untrace_extension" in random_on
    assert 'if [ "$UNTRACE_AUTOMATION" = "1" ]; then' in random_on
    assert "--enable-automation" in random_on
    assert "--disable-background-networking" in random_on
    assert "_read_launch_flags" in random_on
    assert "launch.flags" in random_on
    assert "${_untrace_launch_flags[@]}" in random_on
    assert "AutomationControlled" not in random_on
    assert "--disable-blink-features=AutomationControlled" not in random_on
    assert "--disable-blink-features=*" in random_on
    assert "--disable-blink-features)" in random_on
    assert "--window-size=1920,1080" in random_on
    assert "_untrace_wants_headless" in random_on
    assert "_untrace_runner" in random_on
    assert '_untrace_filtered+=("$arg")' in random_on
    assert "_untrace_load_extensions" in random_on
    assert "--load-extension=*)" in random_on
    assert '"$_untrace_user_data_dir" "${_untrace_load_extensions[@]}"' in random_on

    assert "--disable-extensions)" in random_on
    assert "--disable-extensions-except)" in random_on
    assert "--disable-extensions-except=*)" in random_on
    assert "_untrace_skip_next=1" in random_on

    assert "_untrace_merge_disable_features" in random_on
    assert "_untrace_add_disable_features" in random_on
    assert "DisableLoadExtensionCommandLineSwitch" in random_on
    assert "--disable-features=*)" in random_on


def test_windows_wrapper_strips_extension_allowlist_flags(monkeypatch, tmp_path):
    from untrace.__main__ import build_wrapper_source

    injector.use_untrace_root(tmp_path / "untrace")
    monkeypatch.setattr(
        config, "load", lambda: {"js_injection": True, "chrome_flags": True}
    )
    try:
        src = build_wrapper_source(r"C:\Chrome\chrome_real.exe", random_profile=True)
    finally:
        injector.clear_untrace_root_override()

    assert '"--disable-extensions"' in src
    assert '"--disable-extensions-except="' in src
    assert 'arg == "--disable-extensions-except"' in src
    assert "MergeDisableFeatures" in src
    assert "DisableLoadExtensionCommandLineSwitch" in src
    assert "static readonly List<string> DisableFeatures" in src
    assert "__PROTECT_EXTENSIONS__" not in src


def test_write_launch_flags_persists_flags(tmp_path):
    flags = [CHROME_FLAGS[name] for name in DEFAULT_CHROME_FLAGS]
    path = write_launch_flags(flags, tmp_path)
    assert path.name == LAUNCH_FLAGS_FILE
    saved = path.read_text().splitlines()
    assert all(flag in saved for flag in flags)
    assert "AutomationControlled" in path.read_text()
