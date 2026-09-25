"""Comprobar si un token sigue siendo válido preguntando a su propio servicio.

Cada token solo se envía al servicio que lo emitió (Discord, GitHub...), por HTTPS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import httpx

from envvault.patterns import detect_kind

VALID = "válido"
INVALID = "inválido"
UNKNOWN = "desconocido"


@dataclass
class CheckResult:
    status: str
    detail: str = ""


def _discord(client: httpx.Client, token: str) -> tuple[httpx.Response, str]:
    r = client.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bot {token}"})
    return r, r.json().get("username", "") if r.status_code == 200 else ""


def _discord_webhook(client: httpx.Client, url: str) -> tuple[httpx.Response, str]:
    r = client.get(url)
    return r, r.json().get("name", "") if r.status_code == 200 else ""


def _github(client: httpx.Client, token: str) -> tuple[httpx.Response, str]:
    r = client.get("https://api.github.com/user",
                   headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    return r, r.json().get("login", "") if r.status_code == 200 else ""


def _openai(client: httpx.Client, key: str) -> tuple[httpx.Response, str]:
    return client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}), ""


def _anthropic(client: httpx.Client, key: str) -> tuple[httpx.Response, str]:
    r = client.get("https://api.anthropic.com/v1/models",
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    return r, ""


def _google(client: httpx.Client, key: str) -> tuple[httpx.Response, str]:
    r = client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key})
    return r, ""


def _telegram(client: httpx.Client, token: str) -> tuple[httpx.Response, str]:
    r = client.get(f"https://api.telegram.org/bot{token}/getMe")
    return r, "@" + r.json().get("result", {}).get("username", "") if r.status_code == 200 else ""


CHECKERS: dict[str, Callable[[httpx.Client, str], tuple[httpx.Response, str]]] = {
    "discord_token": _discord,
    "discord_webhook": _discord_webhook,
    "github_token": _github,
    "openai_key": _openai,
    "anthropic_key": _anthropic,
    "google_key": _google,
    "telegram_token": _telegram,
}
# Google responde 400 ("API key not valid") en vez de 401.
INVALID_CODES = {400, 401, 403, 404}


def can_check(value: str) -> bool:
    kind = detect_kind(value)
    return kind is not None and kind.kind in CHECKERS


def check_value(client: httpx.Client, value: str) -> CheckResult | None:
    """None si el tipo de valor no se sabe comprobar."""
    kind = detect_kind(value)
    if kind is None or kind.kind not in CHECKERS:
        return None
    try:
        response, detail = CHECKERS[kind.kind](client, value.strip())
    except httpx.HTTPError as exc:
        return CheckResult(UNKNOWN, f"sin conexión ({type(exc).__name__})")
    except ValueError:
        return CheckResult(UNKNOWN, "respuesta inesperada")
    if response.status_code == 200:
        return CheckResult(VALID, detail)
    if response.status_code == 429:
        return CheckResult(UNKNOWN, "límite de peticiones; prueba luego")
    if response.status_code in INVALID_CODES:
        return CheckResult(INVALID, f"HTTP {response.status_code}")
    return CheckResult(UNKNOWN, f"HTTP {response.status_code}")
