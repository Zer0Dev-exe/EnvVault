import pytest

from envvault.errors import EnvVaultError, NotFound
from envvault.model import Location, VaultData, sanitize_name


def make() -> VaultData:
    data = VaultData()
    data.set(Location(None, None, "MONGO_URI"), "mongodb://db")
    data.set(Location(None, None, "DB_PASS"), "p4ss")
    data.set(Location("HPBot", "dev", "DISCORD_TOKEN"), "tok-dev")
    data.set(Location("HPBot", "dev", "MONGO_URI"), "${compartidos.MONGO_URI}")
    data.set(Location("HPBot", "prod", "DISCORD_TOKEN"), "tok-prod")
    return data


def test_set_get_and_scopes():
    data = make()
    assert data.get(Location("HPBot", "prod", "DISCORD_TOKEN")).value == "tok-prod"
    assert set(data.projects["HPBot"].envs) == {"dev", "prod"}
    assert data.project("hpbot").name == "HPBot"  # sin distinguir mayúsculas
    with pytest.raises(NotFound):
        data.get(Location("HPBot", "prod", "NOPE"))
    with pytest.raises(NotFound):
        data.project("Otro")


def test_update_changes_timestamp_only_when_value_changes():
    data = make()
    loc = Location("HPBot", "dev", "DISCORD_TOKEN")
    secret = data.get(loc)
    secret.updated_at = "2000-01-01T00:00:00+00:00"
    data.set(loc, "tok-dev", note="nota")
    assert secret.updated_at.startswith("2000") and secret.note == "nota"
    data.set(loc, "otro")
    assert not secret.updated_at.startswith("2000")


@pytest.mark.parametrize("key", ["1ABC", "MI-VAR", "con espacio", ""])
def test_invalid_keys(key):
    with pytest.raises(EnvVaultError):
        VaultData().set(Location(None, None, key), "x")


@pytest.mark.parametrize("name", ["compartidos", "Shared", "con espacio", "a.b"])
def test_invalid_project_names(name):
    with pytest.raises(EnvVaultError):
        VaultData().ensure_project(name)


def test_sanitize_name():
    assert sanitize_name("zer0dev-exe.github.io") == "zer0dev-exe-github-io"
    assert sanitize_name("Mi Bot!") == "Mi-Bot"
    assert sanitize_name("compartidos") == "compartidos-proyecto"
    assert sanitize_name("...") == "proyecto"


def test_references():
    data = make()
    data.set(Location("HPBot", "dev", "FULL"), "mongodb://admin:${compartidos.DB_PASS}@host/${DISCORD_TOKEN}")
    data.set(Location("HPBot", "dev", "OTHER"), "${HPBot.prod.DISCORD_TOKEN}")
    data.set(Location("HPBot", "dev", "LITERAL"), "$${compartidos.DB_PASS} y ${HOME}")
    resolved = data.resolve("hpbot", "dev")
    assert resolved["MONGO_URI"] == "mongodb://db"
    assert resolved["FULL"] == "mongodb://admin:p4ss@host/tok-dev"
    assert resolved["OTHER"] == "tok-prod"
    assert resolved["LITERAL"] == "${compartidos.DB_PASS} y ${HOME}"


def test_chained_reference():
    data = make()
    data.set(Location(None, None, "ALIAS"), "${compartidos.MONGO_URI}")
    data.set(Location("HPBot", "dev", "X"), "${shared.ALIAS}")
    assert data.resolve_value(Location("HPBot", "dev", "X")) == "mongodb://db"


def test_missing_reference_is_an_error():
    data = make()
    data.set(Location("HPBot", "dev", "BAD"), "${compartidos.NO_EXISTE}")
    with pytest.raises(EnvVaultError, match="no existe"):
        data.resolve("HPBot", "dev")


def test_circular_reference():
    data = VaultData()
    data.set(Location(None, None, "A"), "${compartidos.B}")
    data.set(Location(None, None, "B"), "${compartidos.A}")
    with pytest.raises(EnvVaultError, match="circular"):
        data.resolve_value(Location(None, None, "A"))


def test_referrers_and_find_value():
    data = make()
    data.set(Location("Otro", "dev", "TOKEN"), "tok-prod")
    assert data.referrers(Location(None, None, "MONGO_URI")) == [Location("HPBot", "dev", "MONGO_URI")]
    assert data.referrers(Location(None, None, "DB_PASS")) == []
    assert set(data.find_value("tok-prod")) == {Location("HPBot", "prod", "DISCORD_TOKEN"), Location("Otro", "dev", "TOKEN")}


def test_serialization_roundtrip():
    data = make()
    data.projects["HPBot"].add_path("C:/bots/hpbot")
    data.set(Location("HPBot", "prod", "DISCORD_TOKEN"), "tok-prod", note="bot real", expires="2027-01-01")
    again = VaultData.from_dict(data.to_dict())
    assert again.to_dict() == data.to_dict()
    assert again.get(Location("HPBot", "prod", "DISCORD_TOKEN")).expires == "2027-01-01"
    assert again.projects["HPBot"].paths == ["C:/bots/hpbot"]


def test_remove():
    data = make()
    data.remove(Location("HPBot", "prod", "DISCORD_TOKEN"))
    assert data.projects["HPBot"].envs["prod"] == {}
    with pytest.raises(NotFound):
        data.remove(Location("HPBot", "prod", "DISCORD_TOKEN"))
    data.remove_project("hpbot")
    assert data.projects == {}
