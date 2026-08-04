import sys

import pytest

from untrace import chromedriver


def test_patch_chromedriver_binary_replaces_cdc_block(tmp_path):
    driver = tmp_path / "chromedriver"
    injection = b"{window.cdc_adoQpoasnfa76pfcZLmcfl_Array = window.Array;};"
    original = (
        b"prefix" + injection + b"enable-automation\x00test-type=webdriver\x00suffix"
    )
    driver.write_bytes(original)
    driver.chmod(0o755)

    assert chromedriver.patch_chromedriver_binary(driver) is True
    patched = driver.read_bytes()
    assert chromedriver.PATCH_MARKER in patched
    assert b"window.cdc_" not in patched
    assert b"test-type=webdriver" not in patched
    if sys.platform == "win32":
        assert b"enable-automation" in patched
    else:
        assert b"enable-automation" not in patched
    assert chromedriver.backup_path(driver).is_file()
    assert chromedriver.patch_chromedriver_binary(driver) is True


def test_patch_chromedriver_binary_returns_false_without_block(tmp_path):
    driver = tmp_path / "chromedriver"
    driver.write_bytes(b"no injection here")
    driver.chmod(0o755)

    assert chromedriver.patch_chromedriver_binary(driver) is False


def test_unpatch_chromedriver_binary_restores_backup(tmp_path):
    driver = tmp_path / "chromedriver"
    injection = b"{window.cdc_adoQpoasnfa76pfcZLmcfl_Array = window.Array;};"
    original = (
        b"prefix" + injection + b"enable-automation\x00test-type=webdriver\x00suffix"
    )
    driver.write_bytes(original)
    driver.chmod(0o755)

    chromedriver.patch_chromedriver_binary(driver)
    assert chromedriver.unpatch_chromedriver_binary(driver) is True
    assert driver.read_bytes() == original
    assert not chromedriver.backup_path(driver).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Linux SUDO_USER home lookup")
def test_unpatch_all_chromedrivers_uses_sudo_user_home(tmp_path, monkeypatch):
    real_user_home = tmp_path / "testuser"
    root_home = tmp_path / "root"
    real_user_home.mkdir()
    root_home.mkdir()

    cache = real_user_home / ".cache" / "selenium" / "chromedriver" / "linux64"
    cache.mkdir(parents=True)
    driver = cache / "chromedriver"
    injection = b"{window.cdc_adoQpoasnfa76pfcZLmcfl_Array = window.Array;};"
    original = injection
    driver.write_bytes(original)
    driver.chmod(0o755)
    chromedriver.patch_chromedriver_binary(driver)

    monkeypatch.setattr(
        chromedriver,
        "home_dirs_to_search",
        lambda: [root_home, real_user_home],
    )

    unpatched = chromedriver.unpatch_all_chromedrivers()
    assert driver in unpatched
    assert driver.read_bytes() == original


def test_find_chromedriver_binaries_searches_wdm_cache(tmp_path, monkeypatch):
    home = tmp_path / "testuser"
    cache = home / ".wdm" / "drivers" / "chromedriver" / "linux64"
    cache.mkdir(parents=True)
    driver = cache / "chromedriver"
    driver.write_bytes(b"\x7fELF fake driver")
    driver.chmod(0o755)

    monkeypatch.setattr(chromedriver, "home_dirs_to_search", lambda: [home])

    assert driver.resolve() in chromedriver.find_chromedriver_binaries()
