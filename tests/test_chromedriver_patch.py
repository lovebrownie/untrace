from untrace import chromedriver_patch


def test_patch_chromedriver_binary_replaces_cdc_block(tmp_path):
    driver = tmp_path / "chromedriver"
    injection = b"{window.cdc_adoQpoasnfa76pfcZLmcfl_Array = window.Array;};"
    original = (
        b"prefix"
        + injection
        + b"enable-automation\x00test-type=webdriver\x00suffix"
    )
    driver.write_bytes(original)
    driver.chmod(0o755)

    assert chromedriver_patch.patch_chromedriver_binary(driver) is True
    patched = driver.read_bytes()
    assert chromedriver_patch.PATCH_MARKER in patched
    assert b"window.cdc_" not in patched
    assert b"enable-automation" not in patched
    assert b"disable-automatio" in patched
    assert chromedriver_patch.backup_path(driver).is_file()
    assert chromedriver_patch.patch_chromedriver_binary(driver) is True


def test_patch_chromedriver_binary_returns_false_without_block(tmp_path):
    driver = tmp_path / "chromedriver"
    driver.write_bytes(b"no injection here")
    driver.chmod(0o755)

    assert chromedriver_patch.patch_chromedriver_binary(driver) is False


def test_unpatch_chromedriver_binary_restores_backup(tmp_path):
    driver = tmp_path / "chromedriver"
    injection = b"{window.cdc_adoQpoasnfa76pfcZLmcfl_Array = window.Array;};"
    original = (
        b"prefix"
        + injection
        + b"enable-automation\x00test-type=webdriver\x00suffix"
    )
    driver.write_bytes(original)
    driver.chmod(0o755)

    chromedriver_patch.patch_chromedriver_binary(driver)
    assert chromedriver_patch.unpatch_chromedriver_binary(driver) is True
    assert driver.read_bytes() == original
    assert not chromedriver_patch.backup_path(driver).exists()


def test_unpatch_all_chromedrivers_uses_sudo_user_home(tmp_path, monkeypatch):
    real_user_home = tmp_path / "carlos"
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
    chromedriver_patch.patch_chromedriver_binary(driver)

    monkeypatch.setattr(chromedriver_patch.Path, "home", lambda: root_home)
    monkeypatch.setenv("SUDO_USER", "carlos")
    monkeypatch.setattr(
        chromedriver_patch.pwd,
        "getpwnam",
        lambda name: type("Pw", (), {"pw_dir": str(real_user_home)})(),
    )

    unpatched = chromedriver_patch.unpatch_all_chromedrivers()
    assert driver in unpatched
    assert driver.read_bytes() == original