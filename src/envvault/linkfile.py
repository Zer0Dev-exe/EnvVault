"""Enlace carpeta ↔ proyecto: un ``.envvault.toml`` sin secretos que se puede subir a git."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from envvault.errors import EnvVaultError
from envvault.model import DEFAULT_ENV

LINK_FILE = ".envvault.toml"


@dataclass
class Link:
    project: str
    env: str
    dir: Path

    @property
    def path(self) -> Path:
        return self.dir / LINK_FILE


def read_link(path: Path) -> Link:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise EnvVaultError(f"{path} no es válido: {exc}") from exc
    project = data.get("project")
    if not isinstance(project, str) or not project:
        raise EnvVaultError(f"{path} no indica el proyecto (project = \"...\").")
    env = data.get("env") or DEFAULT_ENV
    return Link(project, str(env), path.parent)


def find_link(start: Path | None = None) -> Link | None:
    """Busca el enlace en la carpeta y en sus padres, como hace git con .git."""
    folder = (start or Path.cwd()).resolve()
    for candidate in (folder, *folder.parents):
        path = candidate / LINK_FILE
        if path.is_file():
            return read_link(path)
    return None


def write_link(folder: Path, project: str, env: str) -> Path:
    path = folder / LINK_FILE
    # Los nombres ya están validados (letras, números, _ y -): json.dumps da un string TOML válido.
    path.write_text(
        "# Enlace con EnvVault. No contiene secretos: se puede subir a git.\n"
        f"project = {json.dumps(project)}\n"
        f"env = {json.dumps(env)}\n",
        encoding="utf-8",
    )
    return path
