import json

import pytest
from conftest import PASSWORD

from envvault import crypto
from envvault.errors import CorruptVault, EnvVaultError, VaultLocked, VaultNotFound, WrongPassword
from envvault.model import Location
from envvault.store import VaultFile


def test_create_and_unlock_roundtrip(tmp_path):
    file = VaultFile(tmp_path / "v.enc")
    key, code = file.create(PASSWORD)
    assert len(key) == 32
    assert len(code.split("-")) == 8
    reopened = VaultFile(tmp_path / "v.enc")
    assert reopened.unlock(PASSWORD) == key
    assert reopened.load(key).projects == {}


def test_file_does_not_contain_secrets_in_clear(tmp_path):
    file = VaultFile(tmp_path / "v.enc")
    key, _ = file.create(PASSWORD)
    data = file.load(key)
    data.set(Location("HPBot", "prod", "DISCORD_TOKEN"), "super-secreto-123")
    file.save(key, data)
    raw = (tmp_path / "v.enc").read_text(encoding="utf-8")
    assert "super-secreto-123" not in raw
    assert "HPBot" not in raw  # ni siquiera los nombres de proyecto
    assert json.loads(raw)["slots"]["password"]["kdf"]["name"] == "argon2id"


def test_wrong_password(tmp_path):
    file = VaultFile(tmp_path / "v.enc")
    file.create(PASSWORD)
    with pytest.raises(WrongPassword):
        VaultFile(tmp_path / "v.enc").unlock("otra-cosa")


def test_cannot_create_twice(vault_file):
    with pytest.raises(EnvVaultError):
        VaultFile(vault_file.path).create(PASSWORD)


def test_missing_vault(tmp_path):
    with pytest.raises(VaultNotFound):
        VaultFile(tmp_path / "nada.enc").unlock(PASSWORD)


def test_recovery_code(tmp_path):
    file = VaultFile(tmp_path / "v.enc")
    key, code = file.create(PASSWORD)
    # Se tolera escribirla en minúsculas, sin guiones y con 0/1 en vez de O/I.
    sloppy = code.replace("-", " ").lower().replace("o", "0").replace("i", "1")
    assert VaultFile(tmp_path / "v.enc").unlock_with_recovery(sloppy) == key
    with pytest.raises(WrongPassword):
        file.unlock_with_recovery(crypto.new_recovery_code())
    with pytest.raises(WrongPassword):
        file.unlock_with_recovery("no-es-una-clave")


def test_change_password_keeps_data(tmp_path):
    file = VaultFile(tmp_path / "v.enc")
    key, code = file.create(PASSWORD)
    data = file.load(key)
    data.set(Location(None, None, "X"), "valor")
    file.save(key, data)
    file.change_password(key, "nueva-contraseña")
    other = VaultFile(tmp_path / "v.enc")
    with pytest.raises(WrongPassword):
        other.unlock(PASSWORD)
    new_key = other.unlock("nueva-contraseña")
    assert other.load(new_key).shared["X"].value == "valor"
    assert other.unlock_with_recovery(code) == key  # la recuperación sigue valiendo


def test_new_recovery_code_invalidates_old(tmp_path):
    file = VaultFile(tmp_path / "v.enc")
    key, old = file.create(PASSWORD)
    new = file.new_recovery_code(key)
    with pytest.raises(WrongPassword):
        VaultFile(tmp_path / "v.enc").unlock_with_recovery(old)
    assert VaultFile(tmp_path / "v.enc").unlock_with_recovery(new) == key


def test_tampered_payload_is_rejected(tmp_path):
    path = tmp_path / "v.enc"
    file = VaultFile(path)
    key, _ = file.create(PASSWORD)
    header = json.loads(path.read_text(encoding="utf-8"))
    data = bytearray(crypto.b64d(header["payload"]["data"]))
    data[0] ^= 1
    header["payload"]["data"] = crypto.b64e(bytes(data))
    path.write_text(json.dumps(header), encoding="utf-8")
    with pytest.raises(VaultLocked):
        VaultFile(path).load(key)


def test_blocks_cannot_move_between_vaults(tmp_path):
    a, b = tmp_path / "a.enc", tmp_path / "b.enc"
    VaultFile(a).create(PASSWORD)
    VaultFile(b).create(PASSWORD)
    ha = json.loads(a.read_text(encoding="utf-8"))
    hb = json.loads(b.read_text(encoding="utf-8"))
    hb["slots"]["password"] = ha["slots"]["password"]  # misma contraseña, otra bóveda
    b.write_text(json.dumps(hb), encoding="utf-8")
    with pytest.raises(WrongPassword):
        VaultFile(b).unlock(PASSWORD)


def test_session_key_from_other_vault(tmp_path):
    key_a, _ = VaultFile(tmp_path / "a.enc").create(PASSWORD)
    b = VaultFile(tmp_path / "b.enc")
    b.create(PASSWORD)
    with pytest.raises(VaultLocked):
        b.load(key_a)


def test_save_keeps_backup(tmp_path):
    path = tmp_path / "v.enc"
    file = VaultFile(path)
    key, _ = file.create(PASSWORD)
    before = path.read_text(encoding="utf-8")
    data = file.load(key)
    data.set(Location(None, None, "X"), "1")
    file.save(key, data)
    assert file.backup_path.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob(".vault-*.tmp"))


def test_save_detects_replaced_vault(tmp_path):
    path = tmp_path / "v.enc"
    file = VaultFile(path)
    key, _ = file.create(PASSWORD)
    data = file.load(key)
    path.unlink()
    VaultFile(path).create(PASSWORD)
    with pytest.raises(EnvVaultError):
        file.save(key, data)


@pytest.mark.parametrize("content", ["no es json", "{}", '{"format": "envvault", "version": 99, "id": "x"}'])
def test_corrupt_files(tmp_path, content):
    path = tmp_path / "v.enc"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(CorruptVault):
        VaultFile(path).header()


def test_real_argon2_parameters_are_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "DEFAULT_KDF", crypto.KdfParams())
    path = tmp_path / "v.enc"
    VaultFile(path).create(PASSWORD)
    kdf = json.loads(path.read_text(encoding="utf-8"))["slots"]["password"]["kdf"]
    assert (kdf["iterations"], kdf["memory_cost"], kdf["lanes"]) == (3, 65536, 4)
