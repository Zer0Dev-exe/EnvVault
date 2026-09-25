from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from envvault import cli, crypto
from envvault.crypto import KdfParams
from envvault.session import MemorySession
from envvault.store import VaultFile

PASSWORD = "contraseña-segura"
FAST_KDF = KdfParams(iterations=1, memory_cost=64, lanes=1)

# Tokens de prueba montados por partes para que el código fuente no contenga
# nada que parezca un secreto real (y no salten los escáneres de GitHub).
DISCORD = "MTIzNDU2Nzg5MDEyMzQ1Njc4" + "." + "GaBcDe" + "." + "abcdefghijklmnopqrstuvwxyz0123456789ab"
GITHUB = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
OPENAI = "sk-" + "proj-" + "Abcdefghij1234567890Klmnop"
ANTHROPIC = "sk-" + "ant-" + "api03-Abcdefghij1234567890"
GOOGLE = "AI" + "za" + "SyA1234567890abcdefghijklmnopqrstuv"
TELEGRAM = "123456789" + ":" + "AA" + "Hdqwerty1234567890ASDFGHJKLzxcvbn"
MONGO = "mongodb+srv://" + "admin:S3cr3tPass@cluster0.abcde.mongodb.net/db"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Ningún test toca la bóveda real, el llavero real ni el portapapeles."""
    monkeypatch.setenv("ENVVAULT_HOME", str(tmp_path / "home"))
    for name in ("ENVVAULT_PASSWORD", "ENVVAULT_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(crypto, "DEFAULT_KDF", FAST_KDF)
    session = MemorySession()
    monkeypatch.setattr(cli, "session_store", lambda: session)
    copied: list[str] = []
    monkeypatch.setattr("envvault.clipboard.copy_temporarily", lambda text, seconds=30: copied.append(text))
    return {"session": session, "copied": copied}


@pytest.fixture
def session(isolated) -> MemorySession:
    return isolated["session"]


@pytest.fixture
def copied(isolated) -> list[str]:
    return isolated["copied"]


@pytest.fixture
def vault_file(tmp_path) -> VaultFile:
    file = VaultFile()
    file.create(PASSWORD)
    return file


@pytest.fixture
def unlocked(vault_file, session):
    """Bóveda creada y con sesión abierta; devuelve su clave."""
    key = vault_file.unlock(PASSWORD)
    session.store(vault_file.id, key, 15)
    return key


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=True,
    ).stdout


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    return path
