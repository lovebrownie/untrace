from untrace import chromedriver_patch


def test_patch_chromedriver_binary_replaces_cdc_block(tmp_path):
    driver = tmp_path / "chromedriver"
    injection = b"{window.cdc_adoQpoasnfa76pfcZLmcfl_Array = window.Array;};"
    driver.write_bytes(b"prefix" + injection + b"suffix")
    driver.chmod(0o755)

    assert chromedriver_patch.patch_chromedriver_binary(driver) is True
    patched = driver.read_bytes()
    assert chromedriver_patch.PATCH_MARKER in patched
    assert b"window.cdc_" not in patched
    assert chromedriver_patch.patch_chromedriver_binary(driver) is True


def test_patch_chromedriver_binary_returns_false_without_block(tmp_path):
    driver = tmp_path / "chromedriver"
    driver.write_bytes(b"no injection here")
    driver.chmod(0o755)

    assert chromedriver_patch.patch_chromedriver_binary(driver) is False
