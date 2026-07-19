from untrace import selenium


def test_patch_selenium_manager_writes_wrapper(tmp_path):
    binary = tmp_path / "selenium-manager"
    binary.write_bytes(b"\x7fELF fake binary")
    binary.chmod(0o755)

    assert selenium.patch_selenium_manager(binary) is True
    content = binary.read_text(encoding="utf-8")
    assert selenium.PATCH_MARKER in content
    assert selenium.backup_path(binary).is_file()
    assert selenium.patch_selenium_manager(binary) is True


def test_patch_selenium_manager_returns_false_for_missing(tmp_path):
    assert selenium.patch_selenium_manager(tmp_path / "missing") is False


def test_unpatch_selenium_manager_restores_backup(tmp_path):
    binary = tmp_path / "selenium-manager"
    original = b"\x7fELF original binary"
    binary.write_bytes(original)
    binary.chmod(0o755)

    selenium.patch_selenium_manager(binary)
    assert selenium.unpatch_selenium_manager(binary) is True
    assert binary.read_bytes() == original
    assert not selenium.backup_path(binary).exists()


def test_is_patched_detects_wrapper(tmp_path):
    binary = tmp_path / "selenium-manager"
    binary.write_text(f"#!/bin/bash\n# {selenium.PATCH_MARKER}\n")
    assert selenium.is_patched(binary) is True

    binary.write_bytes(b"\x7fELF")
    assert selenium.is_patched(binary) is False
