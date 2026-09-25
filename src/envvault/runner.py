"""Ejecutar un comando con las variables de la bóveda inyectadas en su entorno."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping

from envvault.errors import EnvVaultError


def build_env(values: Mapping[str, str], base: Mapping[str, str] | None = None,
              override: bool = True) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for key, value in values.items():
        if override or key not in env:
            env[key] = value
    return env


def run_command(cmd: list[str], env: Mapping[str, str]) -> int:
    if not cmd:
        raise EnvVaultError("Falta el comando. Ejemplo: envvault run -- node index.js")
    # shutil.which resuelve npm → npm.cmd en Windows, que Popen no encuentra solo.
    exe = shutil.which(cmd[0], path=env.get("PATH")) or cmd[0]
    try:
        process = subprocess.Popen([exe, *cmd[1:]], env=dict(env))
    except FileNotFoundError as exc:
        raise EnvVaultError(f"No se encuentra el comando '{cmd[0]}'.") from exc
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            # El hijo también recibe Ctrl+C: esperamos a que termine y devolvemos su código.
            continue
