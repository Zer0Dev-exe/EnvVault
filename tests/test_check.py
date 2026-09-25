import httpx
import pytest
import respx
from conftest import ANTHROPIC, DISCORD, GITHUB, GOOGLE, TELEGRAM

from envvault.check import INVALID, UNKNOWN, VALID, check_value


@pytest.fixture
def client():
    with httpx.Client() as c:
        yield c


@respx.mock
def test_discord_valid(client):
    route = respx.get("https://discord.com/api/v10/users/@me").respond(200, json={"username": "HPBot"})
    result = check_value(client, DISCORD)
    assert (result.status, result.detail) == (VALID, "HPBot")
    assert route.calls.last.request.headers["Authorization"] == f"Bot {DISCORD}"


@respx.mock
def test_discord_invalid(client):
    respx.get("https://discord.com/api/v10/users/@me").respond(401, json={"message": "401: Unauthorized"})
    assert check_value(client, DISCORD).status == INVALID


@respx.mock
def test_github(client):
    respx.get("https://api.github.com/user").respond(200, json={"login": "Zer0Dev-exe"})
    assert check_value(client, GITHUB).detail == "Zer0Dev-exe"


@respx.mock
def test_anthropic_headers(client):
    route = respx.get("https://api.anthropic.com/v1/models").respond(200, json={"data": []})
    assert check_value(client, ANTHROPIC).status == VALID
    assert route.calls.last.request.headers["x-api-key"] == ANTHROPIC


@respx.mock
def test_google_bad_key_returns_400(client):
    respx.get("https://generativelanguage.googleapis.com/v1beta/models").respond(400)
    assert check_value(client, GOOGLE).status == INVALID


@respx.mock
def test_telegram(client):
    respx.get(f"https://api.telegram.org/bot{TELEGRAM}/getMe").respond(200, json={"result": {"username": "mibot"}})
    assert check_value(client, TELEGRAM).detail == "@mibot"


@respx.mock
def test_rate_limit_and_network_errors(client):
    respx.get("https://api.github.com/user").respond(429)
    assert check_value(client, GITHUB).status == UNKNOWN
    respx.get("https://discord.com/api/v10/users/@me").mock(side_effect=httpx.ConnectError("sin red"))
    result = check_value(client, DISCORD)
    assert result.status == UNKNOWN and "sin conexión" in result.detail


def test_unsupported_values(client):
    assert check_value(client, "hola") is None
    assert check_value(client, "mongodb+srv://a:b@c/d") is None
