"""Leer y escribir ficheros .env (compatible con dotenv de Node y python-dotenv)."""

from __future__ import annotations

import re

LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*[=:]\s?(.*)$")
SAFE_RE = re.compile(r"^[A-Za-z0-9_./:@+,=%-]*$")
QUOTES = ("'", '"', "`")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def _find_close(body: str, quote: str) -> int:
    i = 0
    while i < len(body):
        char = body[i]
        if char == "\\" and quote == '"':
            i += 2
            continue
        if char == quote:
            return i
        i += 1
    return -1


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(0)), text, flags=re.S)


def parse(text: str) -> dict[str, str]:
    """Variables de un .env, en orden. Las líneas que no se entienden se ignoran."""
    lines = text.lstrip("\ufeff").splitlines()
    values: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2).strip()
        if raw[:1] in QUOTES:
            quote, body = raw[0], raw[1:]
            end = _find_close(body, quote)
            # Valores entre comillas de varias líneas (claves privadas, certificados...).
            while end == -1 and i < len(lines):
                body += "\n" + lines[i]
                i += 1
                end = _find_close(body, quote)
            value = body if end == -1 else body[:end]
            if quote == '"':
                value = _unescape(value)
        else:
            value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        values[key] = value
    return values


def quote(value: str) -> str:
    if SAFE_RE.match(value):
        return value
    # Comillas simples: ningún dotenv interpreta $ ni \ dentro de ellas.
    if "'" not in value and "\n" not in value and "\r" not in value:
        return f"'{value}'"
    escaped = (value.replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return f'"{escaped}"'


def dump(values: dict[str, str], header: str | None = None, notes: dict[str, str] | None = None) -> str:
    lines: list[str] = []
    if header:
        lines.extend(f"# {line}" if line else "#" for line in header.splitlines())
        lines.append("")
    for key, value in values.items():
        note = (notes or {}).get(key)
        if note:
            lines.extend(f"# {line}" for line in note.splitlines())
        lines.append(f"{key}={quote(value)}")
    return "\n".join(lines) + "\n"
