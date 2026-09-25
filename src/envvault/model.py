"""Contenido de la bóveda: secretos compartidos y proyectos con sus entornos.

Un valor puede referenciar a otro secreto con ``${compartidos.CLAVE}``,
``${Proyecto.entorno.CLAVE}`` o ``${CLAVE}`` (del mismo entorno). ``$${...}`` deja
el texto tal cual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

from envvault.errors import EnvVaultError, NotFound

SHARED = "compartidos"
SHARED_ALIASES = {"compartidos", "shared"}
DEFAULT_ENV = "dev"
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
REF_RE = re.compile(r"\$(\$?)\{([^{}]*)\}")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_key(key: str) -> None:
    if not KEY_RE.match(key):
        raise EnvVaultError(
            f"Nombre de variable no válido: '{key}' (letras, números y _, sin empezar por número)."
        )


def validate_name(name: str, what: str = "proyecto") -> None:
    if not NAME_RE.match(name):
        raise EnvVaultError(f"Nombre de {what} no válido: '{name}' (letras, números, _ y -).")
    if what == "proyecto" and name.lower() in SHARED_ALIASES:
        raise EnvVaultError(f"'{name}' está reservado para los secretos compartidos.")


def sanitize_name(text: str) -> str:
    """Convierte un nombre de carpeta en un nombre de proyecto válido."""
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-") or "proyecto"
    if name.lower() in SHARED_ALIASES:
        name += "-proyecto"
    return name


@dataclass(frozen=True)
class Location:
    """Dónde vive un secreto. ``project`` es None para los compartidos."""

    project: str | None
    env: str | None
    key: str

    @property
    def scope(self) -> str:
        return SHARED if self.project is None else f"{self.project} · {self.env}"

    def __str__(self) -> str:
        if self.project is None:
            return f"{SHARED}.{self.key}"
        return f"{self.project}.{self.env}.{self.key}"


@dataclass
class Secret:
    value: str
    note: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    expires: str | None = None

    @property
    def is_reference(self) -> bool:
        return any(not m.group(1) for m in REF_RE.finditer(self.value))

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "value": self.value,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.expires:
            data["expires"] = self.expires
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Secret:
        return cls(
            value=str(data["value"]),
            note=str(data.get("note") or ""),
            created_at=str(data.get("created_at") or now_iso()),
            updated_at=str(data.get("updated_at") or now_iso()),
            expires=data.get("expires") or None,
        )


@dataclass
class Project:
    name: str
    envs: dict[str, dict[str, Secret]] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)

    def add_path(self, path: str) -> None:
        if path not in self.paths:
            self.paths.append(path)

    def count(self) -> int:
        return sum(len(secrets) for secrets in self.envs.values())


@dataclass
class VaultData:
    shared: dict[str, Secret] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)

    # ------------------------------------------------------------ serializar
    def to_dict(self) -> dict[str, Any]:
        return {
            "shared": {k: s.to_dict() for k, s in self.shared.items()},
            "projects": {
                name: {
                    "envs": {env: {k: s.to_dict() for k, s in secrets.items()} for env, secrets in p.envs.items()},
                    "paths": list(p.paths),
                }
                for name, p in self.projects.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VaultData:
        shared = {k: Secret.from_dict(v) for k, v in (data.get("shared") or {}).items()}
        projects = {}
        for name, raw in (data.get("projects") or {}).items():
            envs = {
                env: {k: Secret.from_dict(v) for k, v in secrets.items()}
                for env, secrets in (raw.get("envs") or {}).items()
            }
            projects[name] = Project(name, envs, [str(p) for p in raw.get("paths") or []])
        return cls(shared, projects)

    # ------------------------------------------------------------- proyectos
    def find_project(self, name: str) -> Project | None:
        """Busca un proyecto por nombre; si no hay coincidencia exacta, sin distinguir mayúsculas."""
        if name in self.projects:
            return self.projects[name]
        matches = [p for key, p in self.projects.items() if key.lower() == name.lower()]
        return matches[0] if len(matches) == 1 else None

    def project(self, name: str) -> Project:
        project = self.find_project(name)
        if project is None:
            raise NotFound(f"No existe el proyecto '{name}'.")
        return project

    def ensure_project(self, name: str) -> Project:
        project = self.find_project(name)
        if project is None:
            validate_name(name)
            project = self.projects[name] = Project(name)
        return project

    def remove_project(self, name: str) -> Project:
        project = self.project(name)
        del self.projects[project.name]
        return project

    def scope(self, project: str | None, env: str | None, create: bool = False) -> dict[str, Secret]:
        if project is None:
            return self.shared
        proj = self.ensure_project(project) if create else self.project(project)
        env = env or DEFAULT_ENV
        if env not in proj.envs:
            if not create:
                raise NotFound(f"El proyecto '{proj.name}' no tiene el entorno '{env}'.")
            validate_name(env, "entorno")
            proj.envs[env] = {}
        return proj.envs[env]

    def canonical(self, loc: Location) -> Location:
        """Misma ubicación con el nombre de proyecto tal como está guardado."""
        if loc.project is None:
            return Location(None, None, loc.key)
        project = self.find_project(loc.project)
        return Location(project.name if project else loc.project, loc.env or DEFAULT_ENV, loc.key)

    # -------------------------------------------------------------- secretos
    def lookup(self, loc: Location) -> Secret | None:
        try:
            return self.scope(loc.project, loc.env).get(loc.key)
        except NotFound:
            return None

    def get(self, loc: Location) -> Secret:
        secret = self.lookup(loc)
        if secret is None:
            raise NotFound(f"No existe {self.canonical(loc)}.")
        return secret

    def set(self, loc: Location, value: str, note: str | None = None, expires: str | None = None) -> Secret:
        validate_key(loc.key)
        scope = self.scope(loc.project, loc.env, create=True)
        secret = scope.get(loc.key)
        if secret is None:
            secret = scope[loc.key] = Secret(value)
        elif secret.value != value:
            secret.value = value
            secret.updated_at = now_iso()
        if note is not None:
            secret.note = note
        if expires is not None:
            secret.expires = expires or None
        return secret

    def remove(self, loc: Location) -> Secret:
        scope = self.scope(loc.project, loc.env)
        if loc.key not in scope:
            raise NotFound(f"No existe {self.canonical(loc)}.")
        return scope.pop(loc.key)

    def iter_secrets(self) -> Iterator[tuple[Location, Secret]]:
        for key, secret in self.shared.items():
            yield Location(None, None, key), secret
        for project in self.projects.values():
            for env, secrets in project.envs.items():
                for key, secret in secrets.items():
                    yield Location(project.name, env, key), secret

    def find_value(self, value: str) -> list[Location]:
        """Ubicaciones cuyo valor literal es exactamente ``value``."""
        return [loc for loc, secret in self.iter_secrets() if secret.value == value]

    # ----------------------------------------------------------- referencias
    def _target(self, inner: str, current: Location) -> tuple[Location | None, bool]:
        """Destino de ``${inner}`` y si la referencia es estricta (debe existir).

        ``${CLAVE}`` solo cuenta si existe en el mismo entorno; si no, se deja como
        texto (hay .env que usan esa sintaxis para sus propias variables).
        """
        parts = inner.split(".")
        if len(parts) == 1:
            loc = Location(current.project, current.env, parts[0])
            return (loc if self.lookup(loc) else None), False
        if len(parts) == 2 and parts[0].lower() in SHARED_ALIASES:
            return Location(None, None, parts[1]), True
        if len(parts) == 3:
            return self.canonical(Location(*parts)), True
        return None, False

    def _expand(self, value: str, current: Location, stack: tuple[Location, ...]) -> str:
        def replace(match: re.Match[str]) -> str:
            if match.group(1):
                return "${" + match.group(2) + "}"
            target, strict = self._target(match.group(2), current)
            if target is None:
                return match.group(0)
            if target in stack:
                chain = " → ".join(str(loc) for loc in (*stack, target))
                raise EnvVaultError(f"Referencia circular: {chain}")
            secret = self.lookup(target)
            if secret is None:
                if strict:
                    raise EnvVaultError(f"{current}: la referencia {match.group(0)} apunta a un secreto que no existe.")
                return match.group(0)
            return self._expand(secret.value, target, (*stack, target))

        return REF_RE.sub(replace, value)

    def resolve_value(self, loc: Location) -> str:
        loc = self.canonical(loc)
        return self._expand(self.get(loc).value, loc, (loc,))

    def resolve(self, project: str, env: str) -> dict[str, str]:
        proj = self.project(project)
        scope = self.scope(proj.name, env)
        return {key: self.resolve_value(Location(proj.name, env, key)) for key in scope}

    def references(self, loc: Location) -> list[Location]:
        """Ubicaciones a las que apunta directamente el valor de ``loc``."""
        secret = self.lookup(loc)
        if secret is None:
            return []
        targets = []
        for match in REF_RE.finditer(secret.value):
            if match.group(1):
                continue
            target, _ = self._target(match.group(2), loc)
            if target is not None:
                targets.append(target)
        return targets

    def referrers(self, target: Location) -> list[Location]:
        """Secretos cuyo valor referencia a ``target``."""
        target = self.canonical(target)
        return [loc for loc, _ in self.iter_secrets() if target in self.references(loc)]
