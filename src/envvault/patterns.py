"""Patrones de tokens y claves conocidos, para escanear y para validar."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    kind: str
    label: str
    regex: re.Pattern[str]
    group: int = 0
    short: str = ""  # nombre corto para la TUI

    @property
    def name(self) -> str:
        return self.short or self.label


PATTERNS: tuple[Pattern, ...] = (
    Pattern("discord_token", "Token de bot de Discord",
            re.compile(r"\b[MNO][A-Za-z\d_-]{23,27}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,40}\b"), short="Discord"),
    Pattern("discord_webhook", "Webhook de Discord",
            re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d{17,20}/[A-Za-z\d_-]{60,70}"), short="Webhook Discord"),
    Pattern("github_token", "Token de GitHub",
            re.compile(r"\b(?:gh[pousr]_[A-Za-z\d]{36}|github_pat_[A-Za-z\d_]{82})\b"), short="GitHub"),
    Pattern("anthropic_key", "API key de Anthropic", re.compile(r"\bsk-ant-[A-Za-z\d_-]{20,}"), short="Anthropic"),
    Pattern("openai_key", "API key de OpenAI",
            re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z\d_-]{20,}"), short="OpenAI"),
    Pattern("google_key", "API key de Google", re.compile(r"\bAIza[\dA-Za-z_-]{35}(?![\w-])"), short="Google"),
    Pattern("telegram_token", "Token de bot de Telegram", re.compile(r"\b\d{8,10}:AA[A-Za-z\d_-]{33}(?![\w-])"), short="Telegram"),
    Pattern("aws_key", "Access key de AWS", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), short="AWS"),
    Pattern("slack_token", "Token de Slack", re.compile(r"\bxox[abprs]-[A-Za-z\d-]{10,}"), short="Slack"),
    Pattern("slack_webhook", "Webhook de Slack",
            re.compile(r"https://hooks\.slack\.com/services/T[A-Z\d]{8,}/B[A-Z\d]{8,}/[A-Za-z\d]{24}"), short="Webhook Slack"),
    Pattern("stripe_key", "Clave secreta de Stripe", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z\d]{20,}"), short="Stripe"),
    Pattern("stripe_webhook", "Secreto de webhook de Stripe", re.compile(r"\bwhsec_[A-Za-z\d]{32,}"), short="Stripe webhook"),
    Pattern("gitlab_token", "Token de GitLab", re.compile(r"\bglpat-[A-Za-z\d_-]{20}(?![\w-])"), short="GitLab"),
    Pattern("npm_token", "Token de npm", re.compile(r"\bnpm_[A-Za-z\d]{36}\b"), short="npm"),
    Pattern("pypi_token", "Token de PyPI", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z\d_-]{50,}"), short="PyPI"),
    Pattern("huggingface_token", "Token de Hugging Face", re.compile(r"\bhf_[A-Za-z]{34}\b"), short="Hugging Face"),
    Pattern("groq_key", "API key de Groq", re.compile(r"\bgsk_[A-Za-z\d]{52}\b"), short="Groq"),
    Pattern("xai_key", "API key de xAI", re.compile(r"\bxai-[A-Za-z\d]{80}\b"), short="xAI"),
    Pattern("perplexity_key", "API key de Perplexity", re.compile(r"\bpplx-[A-Za-z\d]{48}\b"), short="Perplexity"),
    Pattern("replicate_token", "Token de Replicate", re.compile(r"\br8_[A-Za-z\d]{37}\b"), short="Replicate"),
    Pattern("sendgrid_key", "API key de SendGrid",
            re.compile(r"\bSG\.[A-Za-z\d_-]{22}\.[A-Za-z\d_-]{43}(?![\w-])"), short="SendGrid"),
    Pattern("mailgun_key", "API key de Mailgun", re.compile(r"\bkey-[a-f\d]{32}\b"), short="Mailgun"),
    Pattern("twilio_key", "API key de Twilio", re.compile(r"\bSK[a-f\d]{32}\b"), short="Twilio"),
    Pattern("shopify_token", "Token de Shopify", re.compile(r"\bshp(?:at|ca|pa|ss)_[a-fA-F\d]{32}\b"), short="Shopify"),
    Pattern("digitalocean_token", "Token de DigitalOcean", re.compile(r"\bdo[opr]_v1_[a-f\d]{64}\b"), short="DigitalOcean"),
    Pattern("notion_token", "Token de Notion", re.compile(r"\b(?:secret_[A-Za-z\d]{43}|ntn_[A-Za-z\d]{46})\b"), short="Notion"),
    Pattern("linear_key", "API key de Linear", re.compile(r"\blin_api_[A-Za-z\d]{40}\b"), short="Linear"),
    Pattern("doppler_token", "Token de Doppler", re.compile(r"\bdp\.(?:pt|st|sa|ct|scim|audit)\.[A-Za-z\d]{40,44}\b"), short="Doppler"),
    Pattern("db_uri", "URI de base de datos con contraseña",
            re.compile(r"\b(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|mariadb|mssql|sqlserver|rediss?|amqps?)"
                       r"://[^\s:/@'\"`]+:[^\s@/'\"`]+@[^\s'\"`<>]+"), short="Base de datos"),
    Pattern("private_key", "Clave privada",
            re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"), short="Clave privada"),
    Pattern("assignment", "Posible secreto escrito en el código",
            re.compile(r"(?i)\b(?:token|secret|password|passwd|api_?key|client_?secret)[\"']?\s*[:=]\s*[\"']([^\"'\s]{12,})[\"']"),
            group=1),
)

BY_KIND = {p.kind: p for p in PATTERNS}

PLACEHOLDER_RE = re.compile(
    r"(?i)(your[_-]?|xxxx|changeme|change[_-]me|example|placeholder|dummy|<[^>]*>|\$\{|process\.env|os\.environ|"
    r"tu[_-]?token|aqu[ií]|here|redacted|\*\*\*|user:pass(word)?@|usuario:contrase)"
)
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")


def looks_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_RE.search(value)) or bool(ENV_NAME_RE.match(value))


def detect_kind(value: str) -> Pattern | None:
    """Tipo de un valor completo (p. ej. el de un secreto de la bóveda)."""
    value = value.strip()
    for pattern in PATTERNS:
        if pattern.kind == "assignment":
            continue
        if pattern.kind == "private_key":
            if pattern.regex.search(value):
                return pattern
        elif pattern.regex.fullmatch(value):
            return pattern
    return None


# ----------------------------------------------------------- tipo para mostrar
# ``describe`` solo sirve para la columna «Tipo»: reconoce también valores que no
# son secretos (URL, puerto, ruta…), así que nunca se usa para escanear ni importar.
SERVICE, SECRET, CONFIG = "service", "secret", "config"

_JWT_RE = re.compile(r"eyJ[A-Za-z\d_-]{8,}\.eyJ[A-Za-z\d_-]{8,}\.[A-Za-z\d_-]{16,}")
_DB_SCHEME_RE = re.compile(r"(?i)(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|mariadb|mssql|sqlserver|rediss?|"
                           r"amqps?|sqlite|jdbc:[a-z]+)://")
_URL_RE = re.compile(r"(?i)(?:https?|wss?|ftp)://\S+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_UUID_RE = re.compile(r"(?i)[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}")
_IP_RE = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?")
_HOST_RE = re.compile(r"(?i)(?:localhost|[a-z\d-]+(?:\.[a-z\d-]+)+):\d{1,5}")
_PATH_RE = re.compile(r"(?:\.{1,2}[\\/]|~[\\/]|/(?!/)|[A-Za-z]:[\\/]|\\\\)\S*")
_FILE_RE = re.compile(r"[\w.-]+\.(?:db|sqlite3?|json|ya?ml|toml|env|pem|key|crt|txt|log|csv)", re.I)
_HEX_RE = re.compile(r"(?i)[\da-f]{32,}")
_RANDOM_RE = re.compile(r"[A-Za-z\d_\-+/=.]{20,}")
_BOOL = {"true", "false", "yes", "no", "on", "off", "si", "sí"}
_CERT = {"CERTIFICATE": "Certificado", "PUBLIC KEY": "Clave pública"}


def _key_has(key: str, *words: str) -> bool:
    parts = key.upper().split("_")
    return any(w in parts or key.upper().endswith(w) for w in words)


def describe(value: str, key: str = "") -> tuple[str, str] | None:
    """(nombre corto, categoría) del valor, apoyándose en el nombre de la clave.

    La categoría es SERVICE (credencial de un servicio conocido), SECRET (parece
    un secreto sin servicio concreto) o CONFIG (configuración normal).
    """
    value = value.strip()
    if not value:
        return None
    kind = detect_kind(value)
    if kind is not None:
        return kind.name, SERVICE
    if value.startswith("${") and value.endswith("}"):
        return "Referencia", CONFIG
    if value.startswith("-----BEGIN"):
        header = value.splitlines()[0]
        return next((name for marker, name in _CERT.items() if marker in header), "PEM"), CONFIG
    if _JWT_RE.fullmatch(value):
        return "JWT", SECRET
    if _DB_SCHEME_RE.match(value):
        return "Base de datos", CONFIG
    if _URL_RE.fullmatch(value):
        return ("Webhook", SECRET) if _key_has(key, "WEBHOOK", "HOOK") else ("URL", CONFIG)
    if _EMAIL_RE.fullmatch(value):
        return "Email", CONFIG
    if _UUID_RE.fullmatch(value):
        return "UUID", CONFIG
    if _IP_RE.fullmatch(value):
        return "IP", CONFIG
    if _HOST_RE.fullmatch(value):
        return "Host", CONFIG
    if _PATH_RE.fullmatch(value) or _FILE_RE.fullmatch(value):
        return "Ruta", CONFIG
    # A partir de aquí la forma del valor dice poco: manda el nombre de la clave.
    if _key_has(key, "PASSWORD", "PASS", "PWD", "PASSWD"):
        return "Contraseña", SECRET
    if _key_has(key, "SECRET"):
        return "Secreto", SECRET
    if _key_has(key, "TOKEN"):
        return "Token", SECRET
    if _key_has(key, "KEY", "APIKEY"):
        return "API key", SECRET
    if value.lower() in _BOOL:
        return "Booleano", CONFIG
    if value.isdigit():
        if _key_has(key, "PORT") and 0 < int(value) < 65536:
            return "Puerto", CONFIG
        if _key_has(key, "ID") or 17 <= len(value) <= 20:  # 17-20 cifras: ID de Discord/Twitter
            return "ID", CONFIG
        return "Número", CONFIG
    if re.fullmatch(r"-?\d+\.\d+", value):
        return "Número", CONFIG
    if _key_has(key, "HOST") and " " not in value:
        return "Host", CONFIG
    if _HEX_RE.fullmatch(value):
        return "Hex", SECRET
    if _RANDOM_RE.fullmatch(value) and any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
        return "Secreto", SECRET
    return "Texto", CONFIG


def find_secrets(text: str) -> list[tuple[Pattern, str, int]]:
    """(patrón, valor, posición) de cada secreto aparente en el texto."""
    found: list[tuple[Pattern, str, int]] = []
    seen: set[str] = set()
    for pattern in PATTERNS:
        for match in pattern.regex.finditer(text):
            value = match.group(pattern.group)
            if value in seen or looks_placeholder(value):
                continue
            if pattern.kind == "assignment" and any(v in value or value in v for v in seen):
                continue
            seen.add(value)
            found.append((pattern, value, match.start(pattern.group)))
    return found


def mask(value: str) -> str:
    value = value.strip()
    if value.startswith("-----BEGIN"):
        return value.splitlines()[0]
    if len(value) <= 12:
        return "•" * 8
    return f"{value[:4]}…{value[-4:]}"
