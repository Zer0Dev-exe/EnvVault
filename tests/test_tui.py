import time

import pytest
from conftest import DISCORD, PASSWORD

from envvault.model import Location
from envvault.store import VaultFile
from envvault.tui import ConfirmScreen, EditScreen, EnvVaultApp, ScanScreen
from envvault.vault import Vault
from textual.widgets import DataTable, Input, Static, Tree

SIZE = (140, 40)


@pytest.fixture
def vault(tmp_path):
    file = VaultFile(tmp_path / "v.enc")
    key, _ = file.create(PASSWORD)
    data = file.load(key)
    data.set(Location(None, None, "MONGO_URI"), "mongodb://db", note="base compartida")
    data.set(Location("HPBot", "dev", "DISCORD_TOKEN"), DISCORD, note="bot de pruebas")
    data.set(Location("HPBot", "dev", "DB"), "${compartidos.MONGO_URI}")
    data.set(Location("HPBot", "prod", "DISCORD_TOKEN"), "tok-prod")
    file.save(key, data)
    return Vault(file, key, data)


def make_app(vault, **kwargs):
    copied: list[str] = []
    locked: list[bool] = []
    app = EnvVaultApp(vault, copier=copied.append, on_lock=lambda: locked.append(True), **kwargs)
    return app, copied, locked


async def goto(app, pilot, project, env):
    tree = app.query_one(Tree)

    def find(node):
        if node.data == (project, env):
            return node
        for child in node.children:
            found = find(child)
            if found:
                return found
        return None

    tree.move_cursor(find(tree.root))
    await pilot.pause()


def rows(app):
    return list(app.shown_keys)


def saved(vault):
    return vault.file.load(vault.key)


async def test_starts_on_shared_and_masks_values(vault):
    app, _, _ = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app.scope == (None, None)
        assert rows(app) == ["MONGO_URI"]
        await goto(app, pilot, "HPBot", "dev")
        assert rows(app) == ["DB", "DISCORD_TOKEN"]
        table = app.query_one("#secrets", DataTable)
        cells = [str(table.get_cell_at((i, 1))) for i in range(table.row_count)]
        assert DISCORD not in cells and "${compartidos.MONGO_URI}" in cells


async def test_project_node_selects_first_env(vault):
    app, _, _ = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(app, pilot, "HPBot", None)
        assert app.scope == ("HPBot", "dev")


async def test_reveal_and_copy_resolve_references(vault):
    app, copied, _ = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(app, pilot, "HPBot", "dev")
        app.query_one("#secrets", DataTable).focus()
        await pilot.press("r")
        table = app.query_one("#secrets", DataTable)
        assert str(table.get_cell_at((0, 1))) == "mongodb://db"
        await pilot.press("down", "c")
        assert copied == [DISCORD]
        await pilot.press("r")
        cell = str(table.get_cell_at((1, 1)))
        assert cell.endswith("…") and DISCORD.startswith(cell[:-1])  # recortado en la tabla...
        assert DISCORD in str(app.query_one("#detail", Static).render())  # ...completo en el detalle


async def test_new_secret(vault):
    app, _, _ = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(app, pilot, "HPBot", "prod")
        app.query_one("#secrets", DataTable).focus()
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, EditScreen)
        app.screen.query_one("#key", Input).value = "1MAL"
        await pilot.click("#save")
        await pilot.pause()
        assert "letras" in str(app.screen.query_one("#error", Static).render())
        await pilot.pause(0.3)  # el botón ignora clics durante su animación de pulsado
        app.screen.query_one("#key", Input).value = "CLIENT_ID"
        app.screen.query_one("#value", Input).value = "123"
        app.screen.query_one("#note", Input).value = "id de la app"
        await pilot.click("#save")
        await pilot.pause()
        assert "CLIENT_ID" in rows(app)
        assert saved(vault).get(Location("HPBot", "prod", "CLIENT_ID")).note == "id de la app"


async def test_edit_and_rename(vault):
    app, _, _ = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(app, pilot, "HPBot", "prod")
        app.query_one("#secrets", DataTable).focus()
        await pilot.press("e")
        await pilot.pause()
        assert app.screen.query_one("#value", Input).value == "tok-prod"
        app.screen.query_one("#key", Input).value = "BOT_TOKEN"
        app.screen.query_one("#value", Input).value = "tok-nuevo"
        await pilot.click("#save")
        await pilot.pause()
        data = saved(vault)
        assert data.get(Location("HPBot", "prod", "BOT_TOKEN")).value == "tok-nuevo"
        assert data.lookup(Location("HPBot", "prod", "DISCORD_TOKEN")) is None


async def test_cannot_delete_or_rename_referenced(vault):
    app, _, _ = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.query_one("#secrets", DataTable).focus()
        await pilot.press("x")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmScreen)
        assert "MONGO_URI" in saved(vault).shared


async def test_delete_with_confirmation(vault):
    app, _, _ = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(app, pilot, "HPBot", "prod")
        app.query_one("#secrets", DataTable).focus()
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.click("#cancel")
        await pilot.pause()
        assert rows(app) == ["DISCORD_TOKEN"]
        await pilot.press("x")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert rows(app) == []
        assert saved(vault).projects["HPBot"].envs["prod"] == {}


async def test_search_does_not_trigger_shortcuts(vault):
    app, copied, locked = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(app, pilot, "HPBot", "dev")
        await pilot.press("slash")
        await pilot.press("p", "r", "u", "e", "b", "a", "s", "c", "l", "q")
        await pilot.pause()
        assert app.query_one("#search", Input).value == "pruebasclq"
        assert copied == [] and locked == [] and app.is_running
        app.query_one("#search", Input).value = "pruebas"
        await pilot.pause()
        assert rows(app) == ["DISCORD_TOKEN"]  # busca también en la nota
        await pilot.press("escape")
        await pilot.pause()
        assert rows(app) == ["DB", "DISCORD_TOKEN"]


async def test_lock_key(vault):
    app, _, locked = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
    assert locked == [True]
    assert app.return_value == "locked"


async def test_auto_lock(vault):
    app, _, locked = make_app(vault, lock_at=time.time() + 1.2)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert "se bloquea en" in str(app.query_one("#lock", Static).render())
        await pilot.pause(2.5)
    assert locked == [True]
    assert app.return_value == "timeout"


async def test_scan_project_folders(vault, tmp_path, monkeypatch):
    monkeypatch.setattr("envvault.scan.git_available", lambda: False)
    folder = tmp_path / "hpbot"
    folder.mkdir()
    (folder / "index.js").write_text(f'client.login("{DISCORD}")', encoding="utf-8")
    vault.data.projects["HPBot"].add_path(str(folder))
    app, _, _ = make_app(vault)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await goto(app, pilot, "HPBot", "dev")
        app.query_one("#secrets", DataTable).focus()
        await pilot.press("s")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, ScanScreen)
        assert app.screen.findings[0].vault == ["HPBot.dev.DISCORD_TOKEN"]
        assert "HPBot" in app.flagged
