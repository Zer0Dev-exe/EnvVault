"""Primitivas criptográficas: Argon2id para la contraseña y AES-256-GCM para cifrar.

La bóveda usa cifrado por sobres: una clave de datos aleatoria (DEK) cifra el
contenido, y esa DEK se guarda cifrada dos veces, una con la clave derivada de la
contraseña maestra y otra con la clave de recuperación. Cambiar la contraseña solo
vuelve a cifrar la DEK.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_SIZE = 32
NONCE_SIZE = 12
SALT_SIZE = 16
RECOVERY_BYTES = 20
# Caracteres que no existen en base32 y que se confunden al copiar a mano.
_B32_FIX = str.maketrans({"0": "O", "1": "I", "8": "B"})


@dataclass(frozen=True)
class KdfParams:
    """Coste de Argon2id. ``memory_cost`` va en KiB (65536 = 64 MiB)."""

    iterations: int = 3
    memory_cost: int = 65536
    lanes: int = 4


DEFAULT_KDF = KdfParams()


class DecryptionError(Exception):
    """Clave incorrecta o datos manipulados."""


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def random_key() -> bytes:
    return secrets.token_bytes(KEY_SIZE)


def random_salt() -> bytes:
    return secrets.token_bytes(SALT_SIZE)


def derive_password_key(password: str, salt: bytes, params: KdfParams = DEFAULT_KDF) -> bytes:
    kdf = Argon2id(
        salt=salt,
        length=KEY_SIZE,
        iterations=params.iterations,
        lanes=params.lanes,
        memory_cost=params.memory_cost,
    )
    return kdf.derive(password.encode("utf-8"))


def new_recovery_code() -> str:
    """160 bits aleatorios en base32, en grupos de 4: ``ABCD-EFGH-…`` (8 grupos)."""
    raw = base64.b32encode(secrets.token_bytes(RECOVERY_BYTES)).decode("ascii")
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def parse_recovery_code(code: str) -> bytes:
    cleaned = "".join(code.split()).replace("-", "").upper().translate(_B32_FIX)
    try:
        raw = base64.b32decode(cleaned)
    except ValueError:
        raw = b""
    if len(raw) != RECOVERY_BYTES:
        raise ValueError("La clave de recuperación no tiene el formato correcto (8 grupos de 4 caracteres).")
    return raw


def derive_recovery_key(code: str, salt: bytes) -> bytes:
    # La clave de recuperación ya es aleatoria y larga: basta con HKDF, sin coste extra.
    hkdf = HKDF(algorithm=hashes.SHA256(), length=KEY_SIZE, salt=salt, info=b"envvault recovery")
    return hkdf.derive(parse_recovery_code(code))


def seal(key: bytes, plaintext: bytes, aad: bytes) -> dict[str, str]:
    nonce = secrets.token_bytes(NONCE_SIZE)
    return {"nonce": b64e(nonce), "data": b64e(AESGCM(key).encrypt(nonce, plaintext, aad))}


def unseal(key: bytes, box: dict[str, str], aad: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(b64d(box["nonce"]), b64d(box["data"]), aad)
    except (InvalidTag, KeyError, TypeError, ValueError) as exc:
        raise DecryptionError from exc
