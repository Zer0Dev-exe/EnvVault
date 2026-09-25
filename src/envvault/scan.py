"""Buscar tokens filtrados: en los ficheros de tus carpetas y en el historial de git.

En los repos git solo se miran los ficheros que git no ignora (los que acabarían
subidos). Además se avisa de los .env que están commiteados, o que no están en el
.gitignore y podrían acabar commiteados.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from envvault.gitutil import git_available, run_git
from envvault.importer import SKIP_DIRS, is_env_file
from envvault.patterns import find_secrets, mask

MAX_FILE_SIZE = 1_000_000
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "composer.lock",
    "Gemfile.lock", "uv.lock", ".envvault.toml",
}
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".svg", ".lock")


@dataclass
class Finding:
    kind: str
    label: str
    path: str
    value: str = ""
    line: int | None = None
    commit: str | None = None
    vault: list[str] = field(default_factory=list)

    @property
    def masked(self) -> str:
        return mask(self.value) if self.value else ""

    @property
    def where(self) -> str:
        if self.commit:
            return f"{self.path} @ {self.commit[:8]}"
        return f"{self.path}:{self.line}" if self.line else self.path

    @property
    def source(self) -> str:
        return "historial" if self.commit else "fichero"


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    files: int = 0
    repos: list[Path] = field(default_factory=list)


def skip_file(name: str) -> bool:
    return name in SKIP_FILES or name.endswith(SKIP_SUFFIXES)


class Scanner:
    def __init__(self, vault_values: dict[str, list[str]] | None = None):
        # Valor literal de la bóveda → dónde está guardado ("HPBot.prod.DISCORD_TOKEN").
        self.vault_values = {v: locs for v, locs in (vault_values or {}).items() if len(v) >= 8}

    def scan_text(self, text: str, path: str, commit: str | None = None,
                  line: int | None = None) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[str] = set()

        def line_of(pos: int) -> int | None:
            return line if line is not None else text.count("\n", 0, pos) + 1

        for pattern, value, pos in find_secrets(text):
            seen.add(value)
            findings.append(Finding(pattern.kind, pattern.label, path, value, line_of(pos), commit,
                                    list(self.vault_values.get(value, []))))
        for value, locs in self.vault_values.items():
            if value in seen:
                continue
            pos = text.find(value)
            if pos != -1:
                seen.add(value)
                findings.append(Finding("vault", "Secreto de la bóveda", path, value, line_of(pos), commit, list(locs)))
        return findings

    def scan_file(self, path: Path, shown: str) -> list[Finding]:
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                return []
            raw = path.read_bytes()
        except OSError:
            return []
        if b"\x00" in raw[:8192]:
            return []
        return self.scan_text(raw.decode("utf-8", errors="replace"), shown)

    # --------------------------------------------------------------- carpetas
    def scan_tree(self, root: Path) -> ScanResult:
        root = root.resolve()
        result = ScanResult()
        use_git = git_available()
        stack = [root]
        while stack:
            folder = stack.pop()
            if use_git and (folder / ".git").exists():
                result.repos.append(folder)
                self._scan_repo(folder, root, result)
                continue
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                        stack.append(Path(entry.path))
                elif entry.is_file() and not is_env_file(entry.name) and not skip_file(entry.name):
                    # Fuera de git, los .env son justo donde deben estar los secretos: no se avisan.
                    result.files += 1
                    result.findings.extend(self.scan_file(Path(entry.path), _rel(Path(entry.path), root)))
        return result

    def _scan_repo(self, repo: Path, root: Path, result: ScanResult) -> None:
        tracked = set(run_git(repo, "ls-files", "-z").split("\0")) - {""}
        untracked = set(run_git(repo, "ls-files", "-z", "--others", "--exclude-standard").split("\0")) - {""}
        for rel in sorted(tracked | untracked):
            if rel.endswith("/"):
                nested = repo / rel
                if (nested / ".git").exists():  # un repo dentro de otro (sin ser submódulo)
                    result.repos.append(nested)
                    self._scan_repo(nested, root, result)
                continue
            name = PurePosixPath(rel).name
            shown = _rel(repo / rel, root)
            if is_env_file(name):
                if rel in tracked:
                    result.findings.append(Finding("env_committed", "Fichero .env subido a git", shown))
                else:
                    result.findings.append(Finding("env_unignored", ".env sin proteger en .gitignore", shown))
                    continue
            if skip_file(name):
                continue
            path = repo / rel
            if path.is_file():
                result.files += 1
                result.findings.extend(self.scan_file(path, shown))

    # --------------------------------------------------------------- historial
    def scan_history(self, repo: Path, root: Path | None = None) -> list[Finding]:
        """Secretos añadidos en cualquier commit de cualquier rama (aunque luego se borraran)."""
        output = run_git(repo, "log", "-p", "--all", "--no-color", "--no-ext-diff", "--unified=0",
                         "--format=commit %H")
        prefix = _rel(repo, root) if root is not None and repo != root else ""
        found: dict[tuple[str, str, str], Finding] = {}
        commit: str | None = None
        path: str | None = None
        for line in output.splitlines():
            if line.startswith("commit ") and len(line) == 47:
                commit = line[7:]
            elif line.startswith("+++ "):
                path = line[6:] if line.startswith("+++ b/") else None
                if path and commit and is_env_file(PurePosixPath(path).name):
                    shown = f"{prefix}/{path}" if prefix else path
                    # git log va del más nuevo al más viejo: nos quedamos con el primer commit.
                    found[("env_history", path, "")] = Finding(
                        "env_history", "Fichero .env en el historial de git", shown, commit=commit)
            elif line.startswith("+") and path and commit and not skip_file(PurePosixPath(path).name):
                shown = f"{prefix}/{path}" if prefix else path
                for finding in self.scan_text(line[1:], shown, commit=commit, line=0):
                    finding.line = None
                    found[(finding.kind, path, finding.value)] = finding
        return list(found.values())


def _rel(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root)
    except ValueError:
        return str(path)
    return rel.as_posix() or path.name
