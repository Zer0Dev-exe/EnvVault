"""Lo poco de git que necesita EnvVault (se usa el ejecutable ``git``)."""

from __future__ import annotations

import fnmatch
import shutil
import subprocess
from pathlib import Path

from envvault.errors import EnvVaultError


def git_available() -> bool:
    return shutil.which("git") is not None


def git_root(path: Path) -> Path | None:
    folder = path.resolve()
    for candidate in (folder, *folder.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def run_git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
    except FileNotFoundError as exc:
        raise EnvVaultError("No se encuentra git en el PATH.") from exc
    if result.returncode != 0:
        raise EnvVaultError(f"git {args[0]} ha fallado en {repo}: {result.stderr.strip()}")
    return result.stdout


def is_ignored(path: Path) -> bool:
    root = git_root(path.parent)
    if root is not None and git_available():
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", str(path)],
            capture_output=True, check=False,
        )
        return result.returncode == 0
    gitignore = path.parent / ".gitignore"
    if not gitignore.is_file():
        return False
    # Sin git, una aproximación: alguna línea (sin negaciones) que case con el nombre.
    for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        rule = line.strip().lstrip("/")
        if rule and not rule.startswith(("#", "!")) and fnmatch.fnmatch(path.name, rule):
            return True
    return False


def ensure_ignored(path: Path) -> bool:
    """Añade el fichero al .gitignore de su carpeta si git no lo ignora ya. True si lo añade."""
    if is_ignored(path):
        return False
    gitignore = path.parent / ".gitignore"
    current = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.is_file() else ""
    prefix = "" if not current or current.endswith("\n") else "\n"
    with gitignore.open("a", encoding="utf-8") as fh:
        fh.write(f"{prefix}{path.name}\n")
    return True
