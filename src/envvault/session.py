"""Sesión: la clave de la bóveda guardada un rato en el llavero del sistema.

Así no hay que escribir la contraseña en cada comando. En Windows va al
Administrador de credenciales; en macOS al Llavero; en Linux a Secret Service.
"""

from __future__ import annotations

import json
import os
import time
from typing import Protocol

from envvault import crypto

SERVICE = "envvault"
DEFAULT_MINUTES = 15


def timeout_minutes() -> int:
    try:
        minutes = int(os.environ.get("ENVVAULT_TIMEOUT", DEFAULT_MINUTES))
    except ValueError:
        return DEFAULT_MINUTES
    return minutes if minutes > 0 else DEFAULT_MINUTES


class SessionStore(Protocol):
    def load(self, vault_id: str) -> bytes | None: ...
    def remaining(self, vault_id: str) -> float | None: ...
    def store(self, vault_id: str, key: bytes, minutes: float) -> bool: ...
    def clear(self, vault_id: str) -> bool: ...


class _BaseSession:
    def _get_raw(self, vault_id: str) -> str | None:
        raise NotImplementedError

    def _set_raw(self, vault_id: str, raw: str) -> bool:
        raise NotImplementedError

    def clear(self, vault_id: str) -> bool:
        raise NotImplementedError

    def _entry(self, vault_id: str) -> dict | None:
        raw = self._get_raw(vault_id)
        if not raw:
            return None
        try:
            entry = json.loads(raw)
            float(entry["expires"])
            crypto.b64d(entry["key"])
        except (ValueError, KeyError, TypeError):
            self.clear(vault_id)
            return None
        if entry["expires"] <= time.time():
            self.clear(vault_id)
            return None
        return entry

    def load(self, vault_id: str) -> bytes | None:
        entry = self._entry(vault_id)
        return crypto.b64d(entry["key"]) if entry else None

    def remaining(self, vault_id: str) -> float | None:
        entry = self._entry(vault_id)
        return entry["expires"] - time.time() if entry else None

    def store(self, vault_id: str, key: bytes, minutes: float) -> bool:
        raw = json.dumps({"key": crypto.b64e(key), "expires": time.time() + minutes * 60})
        return self._set_raw(vault_id, raw)


class KeyringSession(_BaseSession):
    # Los backends de keyring lanzan excepciones de tipos muy distintos (según el
    # sistema); si falla cualquier cosa, simplemente no hay sesión.
    def _get_raw(self, vault_id: str) -> str | None:
        try:
            import keyring

            return keyring.get_password(SERVICE, vault_id)
        except Exception:
            return None

    def _set_raw(self, vault_id: str, raw: str) -> bool:
        try:
            import keyring

            keyring.set_password(SERVICE, vault_id, raw)
            return True
        except Exception:
            return False

    def clear(self, vault_id: str) -> bool:
        try:
            import keyring

            keyring.delete_password(SERVICE, vault_id)
            return True
        except Exception:
            return False


class MemorySession(_BaseSession):
    """Sesión en memoria (tests)."""

    def __init__(self) -> None:
        self.entries: dict[str, str] = {}

    def _get_raw(self, vault_id: str) -> str | None:
        return self.entries.get(vault_id)

    def _set_raw(self, vault_id: str, raw: str) -> bool:
        self.entries[vault_id] = raw
        return True

    def clear(self, vault_id: str) -> bool:
        return self.entries.pop(vault_id, None) is not None
