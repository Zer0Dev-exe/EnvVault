"""Fichero de la bóveda: una cabecera en claro (ranuras de clave) y el contenido cifrado.

Formato (JSON)::

    {"format": "envvault", "version": 1, "id": "...",
     "slots": {"password": {"kdf": {...argon2id...}, "key": {nonce, data}},
               "recovery": {"kdf": {...hkdf...}, "key": {nonce, data}}},
     "payload": {nonce, data}}

Cada parte cifrada lleva como datos asociados el id de la bóveda y su papel, así
que no se puede mover un bloque de una bóveda a otra ni de una ranura a otra.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from envvault import crypto
from envvault.crypto import DecryptionError, KdfParams
from envvault.errors import CorruptVault, EnvVaultError, VaultLocked, VaultNotFound, WrongPassword
from envvault.model import VaultData, now_iso

FORMAT = "envvault"
VERSION = 1


def default_home() -> Path:
    custom = os.environ.get("ENVVAULT_HOME")
    return Path(custom).expanduser() if custom else Path.home() / ".envvault"


def default_vault_path() -> Path:
    return default_home() / "vault.enc"


class VaultFile:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_vault_path()
        self._header: dict[str, Any] | None = None

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.name + ".bak")

    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def id(self) -> str:
        return str(self.header()["id"])

    def header(self) -> dict[str, Any]:
        if self._header is None:
            self._header = self._read()
        return self._header

    def _read(self) -> dict[str, Any]:
        if not self.exists():
            raise VaultNotFound(f"No hay ninguna bóveda en {self.path}. Créala con `envvault init`.")
        try:
            header = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CorruptVault(
                f"No se puede leer la bóveda ({exc}). Hay una copia de la versión anterior en {self.backup_path}."
            ) from exc
        if not isinstance(header, dict) or header.get("format") != FORMAT or "id" not in header:
            raise CorruptVault(f"{self.path} no es una bóveda de EnvVault.")
        if header.get("version") != VERSION:
            raise CorruptVault(f"Versión de bóveda no soportada: {header.get('version')}.")
        return header

    def _aad(self, part: str) -> bytes:
        return f"envvault/v{VERSION}/{self.id}/{part}".encode()

    def _slot(self, name: str) -> dict[str, Any]:
        slot = self.header().get("slots", {}).get(name)
        if not isinstance(slot, dict) or not isinstance(slot.get("kdf"), dict):
            raise CorruptVault(f"La bóveda no tiene la ranura de clave '{name}'.")
        return slot

    # ----------------------------------------------------------------- crear
    def create(self, password: str, params: KdfParams | None = None) -> tuple[bytes, str]:
        """Crea una bóveda vacía. Devuelve la clave de datos y la clave de recuperación."""
        if self.exists():
            raise EnvVaultError(f"Ya existe una bóveda en {self.path}.")
        key = crypto.random_key()
        self._header = {"format": FORMAT, "version": VERSION, "id": uuid.uuid4().hex,
                        "created_at": now_iso(), "slots": {}}
        self._set_password_slot(key, password, params or crypto.DEFAULT_KDF)
        code = self._set_recovery_slot(key)
        self._write_payload(key, VaultData())
        return key, code

    def _set_password_slot(self, key: bytes, password: str, params: KdfParams) -> None:
        salt = crypto.random_salt()
        kek = crypto.derive_password_key(password, salt, params)
        self.header()["slots"]["password"] = {
            "kdf": {"name": "argon2id", "salt": crypto.b64e(salt), "iterations": params.iterations,
                    "memory_cost": params.memory_cost, "lanes": params.lanes},
            "key": crypto.seal(kek, key, self._aad("slot/password")),
        }

    def _set_recovery_slot(self, key: bytes) -> str:
        code = crypto.new_recovery_code()
        salt = crypto.random_salt()
        kek = crypto.derive_recovery_key(code, salt)
        self.header()["slots"]["recovery"] = {
            "kdf": {"name": "hkdf-sha256", "salt": crypto.b64e(salt)},
            "key": crypto.seal(kek, key, self._aad("slot/recovery")),
        }
        return code

    # ---------------------------------------------------------------- abrir
    def unlock(self, password: str) -> bytes:
        slot = self._slot("password")
        kdf = slot["kdf"]
        try:
            params = KdfParams(int(kdf["iterations"]), int(kdf["memory_cost"]), int(kdf["lanes"]))
            salt = crypto.b64d(kdf["salt"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptVault("La cabecera de la bóveda está dañada.") from exc
        kek = crypto.derive_password_key(password, salt, params)
        try:
            return crypto.unseal(kek, slot["key"], self._aad("slot/password"))
        except DecryptionError:
            raise WrongPassword("Contraseña incorrecta.") from None

    def unlock_with_recovery(self, code: str) -> bytes:
        slot = self._slot("recovery")
        try:
            salt = crypto.b64d(slot["kdf"]["salt"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptVault("La cabecera de la bóveda está dañada.") from exc
        try:
            kek = crypto.derive_recovery_key(code, salt)
        except ValueError as exc:
            raise WrongPassword(str(exc)) from None
        try:
            return crypto.unseal(kek, slot["key"], self._aad("slot/recovery"))
        except DecryptionError:
            raise WrongPassword("Clave de recuperación incorrecta.") from None

    def load(self, key: bytes) -> VaultData:
        payload = self.header().get("payload")
        if not isinstance(payload, dict):
            raise CorruptVault("La bóveda no tiene contenido.")
        try:
            raw = crypto.unseal(key, payload, self._aad("payload"))
        except DecryptionError:
            raise VaultLocked(
                "La clave no abre esta bóveda (sesión antigua o fichero modificado). Vuelve a desbloquearla."
            ) from None
        try:
            return VaultData.from_dict(json.loads(raw.decode("utf-8")))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise CorruptVault(f"El contenido de la bóveda está dañado ({exc}).") from exc

    # -------------------------------------------------------------- guardar
    def save(self, key: bytes, data: VaultData) -> None:
        self._refresh_header()
        self._write_payload(key, data)

    def change_password(self, key: bytes, new_password: str, params: KdfParams | None = None) -> None:
        self._refresh_header()
        self.load(key)  # comprueba que la clave es la de esta bóveda
        self._set_password_slot(key, new_password, params or crypto.DEFAULT_KDF)
        self._write()

    def new_recovery_code(self, key: bytes) -> str:
        self._refresh_header()
        self.load(key)
        code = self._set_recovery_slot(key)
        self._write()
        return code

    def _refresh_header(self) -> None:
        """Relee la cabecera por si otro proceso cambió la contraseña mientras tanto."""
        current = self._read()
        if self._header is not None and current["id"] != self._header["id"]:
            raise EnvVaultError("La bóveda se ha sustituido por otra mientras estaba abierta; vuelve a abrirla.")
        self._header = current

    def _write_payload(self, key: bytes, data: VaultData) -> None:
        raw = json.dumps(data.to_dict(), ensure_ascii=False).encode("utf-8")
        header = self.header()
        header["payload"] = crypto.seal(key, raw, self._aad("payload"))
        header["updated_at"] = now_iso()
        self._write()

    def _write(self) -> None:
        """Escritura atómica: fichero temporal + rename, guardando la versión anterior en .bak."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.header(), indent=2)
        fd, tmp = tempfile.mkstemp(prefix=".vault-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            if self.exists():
                shutil.copy2(self.path, self.backup_path)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)
