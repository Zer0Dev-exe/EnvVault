import json

import pytest
from conftest import DISCORD

from envvault import importer
from envvault.model import Location, VaultData


@pytest.mark.parametrize("name,expected", [
    (".env", ("dev", 0)),
    (".env.local", ("dev", 2)),
    (".env.development", ("dev", 1)),
    (".env.production", ("prod", 1)),
    (".env.production.local", ("prod", 3)),
    (".env.test", ("test", 1)),
    (".env.example", None),
    (".env.sample", None),
    (".env.production.example", None),
    ("env", None),
    (".envrc", None),
    (".env.", None),
])
def test_classify_env_file(name, expected):
    assert importer.classify_env_file(name) == expected


def test_to_env_key():
    assert importer.to_env_key(["clientId"]) == "CLIENT_ID"
    assert importer.to_env_key(["discord", "botToken"]) == "DISCORD_BOT_TOKEN"
    assert importer.to_env_key(["mongo-uri"]) == "MONGO_URI"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "proyectos"
    write(root / "HPBot" / ".env", "DISCORD_TOKEN=tok\nCLIENT_ID=1\n")
    write(root / "HPBot" / ".env.local", "DISCORD_TOKEN=tok-local\n")
    write(root / "HPBot" / ".env.production", "DISCORD_TOKEN=tok-prod\n")
    write(root / "HPBot" / ".env.example", "DISCORD_TOKEN=\n")
    write(root / "HPBot" / "node_modules" / "lib" / ".env", "NO=1\n")
    write(root / "zer0dev-exe.github.io" / ".env", "GA_ID=G-123\n")
    write(root / "a" / "api" / ".env", "X=1\n")
    write(root / "b" / "api" / ".env", "X=2\n")
    write(root / "ModMail" / "config.json", json.dumps({
        "token": DISCORD, "prefix": "!", "mongo": {"uri": "mongodb://u:p4ss@h/db"}, "owner": "123",
        "apiKey": "your-api-key-here",
    }))
    write(root / "vacio" / ".env", "# nada\n")
    return root


def test_discover(projects):
    found = importer.discover(projects)
    summary = [(f.project, f.env, f.path.name) for f in found]
    assert ("HPBot", "dev", ".env") in summary
    assert ("HPBot", "dev", ".env.local") in summary
    assert ("HPBot", "prod", ".env.production") in summary
    assert not any(f.path.name == ".env.example" for f in found)
    assert not any("node_modules" in f.path.parts for f in found)
    assert ("zer0dev-exe-github-io", "dev", ".env") in summary
    api_names = {f.project for f in found if f.path.parent.name == "api"}
    assert len(api_names) == 2 and "api" in api_names  # el segundo lleva el nombre del padre
    modmail = next(f for f in found if f.project == "ModMail")
    assert modmail.kind == "json"
    assert modmail.values == {"TOKEN": DISCORD, "MONGO_URI": "mongodb://u:p4ss@h/db"}
    assert not any(f.project == "vacio" for f in found)
    # Dentro de un mismo proyecto y entorno, los de más prioridad van después.
    hp_dev = [f.path.name for f in found if f.project == "HPBot" and f.env == "dev"]
    assert hp_dev == [".env", ".env.local"]


def test_discover_without_json(projects):
    assert not any(f.kind == "json" for f in importer.discover(projects, include_json=False))


def test_apply_merges_by_priority(projects):
    data = VaultData()
    report = importer.apply(data, importer.discover(projects))
    assert data.get(Location("HPBot", "dev", "DISCORD_TOKEN")).value == "tok-local"
    assert data.get(Location("HPBot", "prod", "DISCORD_TOKEN")).value == "tok-prod"
    assert data.get(Location("HPBot", "dev", "CLIENT_ID")).value == "1"
    assert not report.conflicts
    assert str(projects / "HPBot") in data.projects["HPBot"].paths


def test_apply_does_not_overwrite_without_flag(projects):
    data = VaultData()
    data.set(Location("HPBot", "prod", "DISCORD_TOKEN"), "otro")
    data.set(Location("HPBot", "dev", "CLIENT_ID"), "1")
    report = importer.apply(data, importer.discover(projects))
    assert data.get(Location("HPBot", "prod", "DISCORD_TOKEN")).value == "otro"
    assert [str(loc) for loc, _ in report.conflicts] == ["HPBot.prod.DISCORD_TOKEN"]
    assert Location("HPBot", "dev", "CLIENT_ID") in report.unchanged

    report = importer.apply(data, importer.discover(projects), overwrite=True)
    assert data.get(Location("HPBot", "prod", "DISCORD_TOKEN")).value == "tok-prod"
    assert not report.conflicts


def test_apply_is_idempotent(projects):
    data = VaultData()
    importer.apply(data, importer.discover(projects))
    report = importer.apply(data, importer.discover(projects))
    assert not report.added and not report.updated and not report.conflicts
