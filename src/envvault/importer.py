"""Encontrar los .env (y config.json con tokens) de una carpeta de proyectos e importarlos."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from envvault import dotenv
from envvault.model import DEFAULT_ENV, Location, VaultData, sanitize_name
from envvault.patterns import detect_kind, looks_placeholder

SKIP_DIRS = {
    "node_modules", "__pycache__", "venv", "dist", "build", "target", "vendor", "site-packages", "bower_components",
}
IGNORED_VARIANTS = {
    "example", "sample", "template", "dist", "defaults", "default", "schema", "tpl", "bak", "backup", "old",
}
ENV_NAMES = {"": DEFAULT_ENV, "development": DEFAULT_ENV, "dev": DEFAULT_ENV, "production": "prod", "prod": "prod"}
JSON_FILES = {"config.json", "secrets.json"}
SECRETISH_RE = re.compile(
    r"(?i)(token|secret|passw|api[_-]?key|apikey|webhook|dsn|uri\b|_uri|mongo|database[_-]?url|client[_-]?id|private[_-]?key)"
)


@dataclass
class Found:
    path: Path
    project: str
    env: str
    values: dict[str, str]
    kind: str  # "env" o "json"
    priority: int = 0


@dataclass
class ImportReport:
    added: list[Location] = field(default_factory=list)
    updated: list[Location] = field(default_factory=list)
    unchanged: list[Location] = field(default_factory=list)
    conflicts: list[tuple[Location, Path]] = field(default_factory=list)


def classify_env_file(name: str) -> tuple[str, int] | None:
    """(entorno, prioridad) de un fichero .env, o None si no es uno (o es una plantilla).

    ``.env`` < ``.env.production`` < ``.env.local`` < ``.env.production.local``, como en Next.js/Vite.
    """
    if name == ".env":
        return DEFAULT_ENV, 0
    if not name.startswith(".env."):
        return None
    parts = name[5:].lower().split(".")
    if not all(parts) or any(part in IGNORED_VARIANTS for part in parts):
        return None
    local = parts[-1] == "local"
    if local:
        parts = parts[:-1]
    if len(parts) > 1:
        return None
    variant = parts[0] if parts else ""
    env = ENV_NAMES.get(variant) or sanitize_name(variant)
    return env, (1 if variant else 0) + (2 if local else 0)


def is_env_file(name: str) -> bool:
    return classify_env_file(name) is not None


def to_env_key(parts: list[str]) -> str:
    words = [re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", part) for part in parts]
    key = re.sub(r"[^A-Za-z0-9]+", "_", "_".join(words)).strip("_").upper()
    return f"_{key}" if key[:1].isdigit() else key


def json_secrets(path: Path) -> dict[str, str]:
    """Valores con pinta de secreto de un config.json (hasta dos niveles de anidación)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    values: dict[str, str] = {}

    def walk(obj: dict, prefix: list[str]) -> None:
        for key, value in obj.items():
            if isinstance(value, dict) and len(prefix) < 2:
                walk(value, [*prefix, str(key)])
            elif (isinstance(value, str) and value.strip() and not looks_placeholder(value)
                  and (SECRETISH_RE.search(str(key)) or detect_kind(value))):
                values[to_env_key([*prefix, str(key)])] = value

    if isinstance(data, dict):
        walk(data, [])
    return values


def discover(root: Path, include_json: bool = True, max_depth: int = 6) -> list[Found]:
    root = root.resolve()
    found: list[Found] = []
    folder_names: dict[Path, str] = {}
    used: dict[str, Path] = {}

    def project_name(folder: Path) -> str:
        if folder not in folder_names:
            name = sanitize_name(folder.name)
            if name.lower() in used and used[name.lower()] != folder:
                name = sanitize_name(f"{folder.parent.name}-{folder.name}")
            used.setdefault(name.lower(), folder)
            folder_names[folder] = name
        return folder_names[folder]

    for dirpath, dirnames, filenames in os.walk(root):
        folder = Path(dirpath)
        depth = len(folder.relative_to(root).parts)
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") and depth < max_depth
        )
        for name in sorted(filenames):
            path = folder / name
            env_info = classify_env_file(name)
            if env_info:
                try:
                    values = dotenv.parse(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                if values:
                    found.append(Found(path, project_name(folder), env_info[0], values, "env", env_info[1]))
            elif include_json and name.lower() in JSON_FILES:
                values = json_secrets(path)
                if values:
                    found.append(Found(path, project_name(folder), DEFAULT_ENV, values, "json", -1))
    found.sort(key=lambda f: (f.project.lower(), f.env, f.priority))
    return found


def apply(data: VaultData, founds: list[Found], overwrite: bool = False) -> ImportReport:
    """Mete lo encontrado en la bóveda. Sin ``overwrite``, no pisa valores distintos ya guardados.

    Dentro de la misma importación, un fichero de más prioridad (``.env.local``) sí pisa
    al de menos (``.env``).
    """
    # Primero el valor efectivo de cada variable (el del fichero de más prioridad)...
    merged: dict[Location, tuple[str, Path]] = {}
    for found in sorted(founds, key=lambda f: f.priority):
        project = data.ensure_project(found.project)
        project.add_path(str(found.path.parent))
        for key, value in found.values.items():
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                merged[Location(project.name, found.env, key)] = (value, found.path)
    # ...y después se compara con lo que ya hay en la bóveda.
    report = ImportReport()
    for loc, (value, path) in merged.items():
        current = data.lookup(loc)
        if current is None:
            data.set(loc, value)
            report.added.append(loc)
        elif current.value == value:
            report.unchanged.append(loc)
        elif overwrite:
            data.set(loc, value)
            report.updated.append(loc)
        else:
            report.conflicts.append((loc, path))
    return report
