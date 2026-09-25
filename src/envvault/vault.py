"""Bóveda abierta: fichero + clave + contenido descifrado."""

from __future__ import annotations

from dataclasses import dataclass

from envvault.model import VaultData
from envvault.store import VaultFile


@dataclass
class Vault:
    file: VaultFile
    key: bytes
    data: VaultData

    def save(self) -> None:
        self.file.save(self.key, self.data)

    def secret_values(self, min_length: int = 8) -> dict[str, list[str]]:
        """Valor literal → ubicaciones, para reconocer secretos de la bóveda al escanear."""
        values: dict[str, list[str]] = {}
        for loc, secret in self.data.iter_secrets():
            value = secret.value.strip()
            if len(value) >= min_length and not secret.is_reference:
                values.setdefault(value, []).append(str(loc))
        return values
