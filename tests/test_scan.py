import pytest
from conftest import ANTHROPIC, DISCORD, GITHUB, GOOGLE, MONGO, OPENAI, TELEGRAM, git, make_repo

from envvault.patterns import CONFIG, SECRET, SERVICE, describe, detect_kind, find_secrets, mask
from envvault.scan import Scanner


@pytest.mark.parametrize("value,kind", [
    (DISCORD, "discord_token"),
    (GITHUB, "github_token"),
    (OPENAI, "openai_key"),
    (ANTHROPIC, "anthropic_key"),
    (GOOGLE, "google_key"),
    (TELEGRAM, "telegram_token"),
    (MONGO, "db_uri"),
    ("AK" + "IAABCDEFGHIJKLMNOP", "aws_key"),
    ("https://discord.com/api/webhooks/123456789012345678/" + "a" * 68, "discord_webhook"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----", "private_key"),
])
def test_detect_kind(value, kind):
    assert detect_kind(value).kind == kind


# Montados por partes, como en conftest, para no parecer secretos reales.
@pytest.mark.parametrize("value,kind", [
    ("glp" + "at-" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn", "gitlab_token"),
    ("np" + "m_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", "npm_token"),
    ("h" + "f_" + "AbCdEfGhIjKlMnOpQrStUvWxYzAbCdEfGh", "huggingface_token"),
    ("gs" + "k_" + "A1b2C3d4" * 6 + "E5f6", "groq_key"),
    ("S" + "G." + "A1b2C3d4E5f6G7h8I9j0K1" + "." + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v", "sendgrid_key"),
    ("sk" + "_test_" + "A1b2C3d4E5f6G7h8I9j0K1l2", "stripe_key"),
    ("whs" + "ec_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6", "stripe_webhook"),
    ("https://hooks.slack.com/services/" + "T0123ABCD/B0123ABCD/" + "A1b2C3d4E5f6G7h8I9j0K1l2", "slack_webhook"),
    ("do" + "p_v1_" + "a1b2c3d4" * 8, "digitalocean_token"),
    ("rediss://" + "default:S3cr3t@cache.example.com:6380", "db_uri"),
])
def test_detect_more_services(value, kind):
    assert detect_kind(value).kind == kind


@pytest.mark.parametrize("key,value,name,category", [
    ("DISCORD_TOKEN", DISCORD, "Discord", SERVICE),
    ("CLIENT_ID", "155123456789012240", "ID", CONFIG),
    ("GUILD", "155123456789012240", "ID", CONFIG),
    ("CLIENT_SECRET", "s3cr3t-abcdefghijk", "Secreto", SECRET),
    ("DB_PASSWORD", "1234", "Contraseña", SECRET),
    ("SESSION_TOKEN", "abc", "Token", SECRET),
    ("MAPS_API_KEY", "qwerty", "API key", SECRET),
    ("DASHBOARD_PORT", "3000", "Puerto", CONFIG),
    ("MAX_USERS", "50", "Número", CONFIG),
    ("RATIO", "0.75", "Número", CONFIG),
    ("DEBUG", "true", "Booleano", CONFIG),
    ("DASHBOARD_URL", "http://localhost:3000", "URL", CONFIG),
    ("ALERTS_WEBHOOK", "https://example.com/hook/abc", "Webhook", SECRET),
    ("MONGO_URI", "mongodb://localhost/db", "Base de datos", CONFIG),
    ("MONGO_URI", MONGO, "Base de datos", SERVICE),
    ("DATABASE_PATH", "./data/jarvis.db", "Ruta", CONFIG),
    ("LOG_DIR", r"C:\Users\yo\logs", "Ruta", CONFIG),
    ("DB_FILE", "jarvis.sqlite", "Ruta", CONFIG),
    ("SECRET_KEY_PATH", "./keys/app.pem", "Ruta", CONFIG),
    ("ADMIN_EMAIL", "yo@example.com", "Email", CONFIG),
    ("TENANT", "123e4567-e89b-12d3-a456-426614174000", "UUID", CONFIG),
    ("SERVER", "192.168.1.10:8080", "IP", CONFIG),
    ("REDIS", "cache.local:6379", "Host", CONFIG),
    ("DB_HOST", "localhost", "Host", CONFIG),
    ("SUPABASE_ANON", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.abcdefghijklmnopqrstuvwxyz", "JWT", SECRET),
    ("SIGNING", "a1b2c3d4" * 4, "Hex", SECRET),
    ("OTHER", "A1b2C3d4E5f6G7h8I9j0K1", "Secreto", SECRET),
    ("DB", "${compartidos.MONGO_URI}", "Referencia", CONFIG),
    ("CERT", "-----BEGIN CERTIFICATE-----\nabc", "Certificado", CONFIG),
    ("BOT_NAME", "Jarvis", "Texto", CONFIG),
])
def test_describe(key, value, name, category):
    assert describe(value, key) == (name, category)


def test_describe_empty():
    assert describe("   ") is None


@pytest.mark.parametrize("value", ["hola", "1234", "mongodb://localhost/db", "sk-corto"])
def test_detect_kind_nothing(value):
    assert detect_kind(value) is None


def test_find_secrets_in_code():
    code = f"""
const client = new Client();
client.login("{DISCORD}");
const cfg = {{ apiKey: "{OPENAI}", token: "your-token-here" }};
const db = "mongodb://user:password@localhost/db";
password = "{"x" * 4}realpassword123"
secret: "DISCORD_TOKEN"
"""
    kinds = [(p.kind, v) for p, v, _ in find_secrets(code)]
    assert ("discord_token", DISCORD) in kinds
    assert ("openai_key", OPENAI) in kinds
    assert not any(v == "your-token-here" for _, v in kinds)
    assert not any(k == "db_uri" for k, _ in kinds)  # user:password es un ejemplo
    assert ("assignment", "xxxxrealpassword123") not in kinds  # "xxxx" es de relleno
    assert not any(v == "DISCORD_TOKEN" for _, v in kinds)
    # El apiKey no sale dos veces (como OpenAI y como asignación).
    assert sum(1 for _, v in kinds if v == OPENAI) == 1


def test_mask():
    assert mask(DISCORD) == "MTIz…89ab"
    assert mask("corto") == "••••••••"


def test_scan_tree_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr("envvault.scan.git_available", lambda: False)
    (tmp_path / "bot").mkdir()
    (tmp_path / "bot" / "index.js").write_text(f'client.login("{DISCORD}")\n', encoding="utf-8")
    (tmp_path / "bot" / ".env").write_text(f"TOKEN={DISCORD}\n", encoding="utf-8")  # sitio correcto
    (tmp_path / "bot" / "node_modules").mkdir()
    (tmp_path / "bot" / "node_modules" / "x.js").write_text(f'"{GITHUB}"', encoding="utf-8")
    (tmp_path / "bot" / "logo.png").write_bytes(b"\x89PNG\x00\x00" + DISCORD.encode())
    result = Scanner({DISCORD: ["HPBot.prod.DISCORD_TOKEN"]}).scan_tree(tmp_path)
    assert [(f.kind, f.where) for f in result.findings] == [("discord_token", "bot/index.js:1")]
    assert result.findings[0].vault == ["HPBot.prod.DISCORD_TOKEN"]


def test_scan_finds_vault_values_without_known_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr("envvault.scan.git_available", lambda: False)
    (tmp_path / "config.py").write_text("\n\nPASS = 'mi-clave-rara-777'\n", encoding="utf-8")
    result = Scanner({"mi-clave-rara-777": ["compartidos.PASS"]}).scan_tree(tmp_path)
    assert [(f.kind, f.line, f.vault) for f in result.findings] == [("vault", 3, ["compartidos.PASS"])]


def test_scan_git_repo(tmp_path):
    repo = make_repo(tmp_path / "bot")
    (repo / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    (repo / "secret.txt").write_text(GITHUB, encoding="utf-8")  # ignorado: no se sube
    (repo / ".env").write_text(f"TOKEN={DISCORD}\n", encoding="utf-8")  # sin ignorar
    (repo / ".env.production").write_text("X=1\n", encoding="utf-8")
    (repo / "app.py").write_text(f'KEY = "{ANTHROPIC}"\n', encoding="utf-8")
    git(repo, "add", ".env.production", "app.py", ".gitignore")
    git(repo, "commit", "-q", "-m", "init")
    result = Scanner().scan_tree(tmp_path)
    found = {(f.kind, f.path) for f in result.findings}
    assert found == {
        ("env_unignored", "bot/.env"),
        ("env_committed", "bot/.env.production"),
        ("anthropic_key", "bot/app.py"),
    }
    assert result.repos == [repo.resolve()] or result.repos == [repo]


def test_scan_history_finds_deleted_secrets(tmp_path):
    repo = make_repo(tmp_path / "bot")
    (repo / "config.json").write_text(f'{{"token": "{DISCORD}"}}\n', encoding="utf-8")
    (repo / ".env").write_text("A=1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "oops")
    first = git(repo, "rev-parse", "HEAD").strip()
    (repo / "config.json").write_text('{"token": ""}\n', encoding="utf-8")
    git(repo, "rm", "-q", "--cached", ".env")
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "arreglado")
    assert Scanner().scan_tree(repo).findings == []  # hoy está limpio...
    history = Scanner({DISCORD: ["HPBot.dev.TOKEN"]}).scan_history(repo)
    kinds = {(f.kind, f.path, f.commit) for f in history}
    assert ("discord_token", "config.json", first) in kinds  # ...pero el historial no
    assert ("env_history", ".env", first) in kinds
    token = next(f for f in history if f.kind == "discord_token")
    assert token.vault == ["HPBot.dev.TOKEN"] and token.where == f"config.json @ {first[:8]}"
