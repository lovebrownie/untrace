from untrace import selenium_manager_patch


def test_patch_selenium_manager_writes_wrapper(tmp_path):
    binary = tmp_path / "selenium-manager"
    binary.write_bytes(b"\x7fELF fake binary")
    binary.chmod(0o755)

    assert selenium_manager_patch.patch_selenium_manager(binary) is True
    content = binary.read_text(encoding="utf-8")
    assert selenium_manager_patch.PATCH_MARKER in content
    assert selenium_manager_patch.backup_path(binary).is_file()
    assert selenium_manager_patch.patch_selenium_manager(binary) is True


def test_patch_selenium_manager_returns_false_for_missing(tmp_path):
    assert selenium_manager_patch.patch_selenium_manager(tmp_path / "missing") is False


def test_unpatch_selenium_manager_restores_backup(tmp_path):
    binary = tmp_path / "selenium-manager"
    original = b"\x7fELF original binary"
    binary.write_bytes(original)
    binary.chmod(0o755)

    selenium_manager_patch.patch_selenium_manager(binary)
    assert selenium_manager_patch.unpatch_selenium_manager(binary) is True
    assert binary.read_bytes() == original
    assert not selenium_manager_patch.backup_path(binary).exists()


def test_is_patched_detects_wrapper(tmp_path):
    binary = tmp_path / "selenium-manager"
    binary.write_text(f"#!/bin/bash\n# {selenium_manager_patch.PATCH_MARKER}\n")
    assert selenium_manager_patch.is_patched(binary) is True

    binary.write_bytes(b"\x7fELF")
    assert selenium_manager_patch.is_patched(binary) is False