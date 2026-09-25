import sys

import pytest
from conftest import DISCORD, PASSWORD, git, make_repo
from typer.testing import CliRunner

from envvault import cli, dotenv
from envvault.errors import VaultLocked
from envvault.linkfile import LINK_FILE, find_link
from envvault.model import Location
from envvault.store import VaultFile

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    # Tablas anchas: que las rutas no se partan en varias líneas.
    monkeypatch.setattr(cli.console, "width", 200)
    monkeypatch.setattr(cli.err_console, "width", 200)


def invoke(*args, input=None):
    return runner.invoke(cli.app, list(args), input=input, catch_exceptions=False)


def data_of(file: VaultFile):
    return file.load(file.unlock(PASSWORD))


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    folder = tmp_path / "HPBot"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def test_no_vault_message():
    result = invoke()
    assert result.exit_code == 0
    assert "envvault init" in result.output


def test_init_creates_vault_and_session(session):
    result = invoke("init", input="corta\ncorta\n" + f"{PASSWORD}\n{PASSWORD}\n")
    assert result.exit_code == 0, result.output
    assert "al menos 8" in result.output
    assert "Clave de recuperación" in result.output
    file = VaultFile()
    assert file.exists()
    assert session.load(file.id) == file.unlock(PASSWORD)
    assert invoke("init").exit_code == 1


def test_set_get_ls(unlocked, workdir, copied):
    assert invoke("set", "TOKEN", DISCORD, "-p", "HPBot", "-e", "prod", "--note", "bot real").exit_code == 0
    result = invoke("get", "TOKEN", "-p", "hpbot", "-e", "prod", "--raw")
    assert result.output.strip() == DISCORD
    result = invoke("get", "TOKEN", "-p", "HPBot", "-e", "prod")
    assert copied == [DISCORD] and "copiado" in result.output
    result = invoke("ls", "HPBot")
    assert "TOKEN" in result.output and "Discord" in result.output
    assert DISCORD not in result.output  # enmascarado
    assert "HPBot" in invoke("ls").output


def test_set_forms_and_errors(unlocked, workdir):
    assert invoke("set", "A=1", "--shared").exit_code == 0
    assert invoke("set", "B", "--shared", input="desde-stdin\n").exit_code == 0
    data = data_of(VaultFile())
    assert data.shared["A"].value == "1" and data.shared["B"].value == "desde-stdin"
    result = invoke("set", "X", "1")  # carpeta sin enlazar
    assert result.exit_code == 1 and "no está enlazada" in result.output
    assert invoke("set", "1MAL", "x", "--shared").exit_code == 1
    assert invoke("set", "C", "x", "--shared", "--expires", "mañana").exit_code == 1


def test_set_hints_duplicate_values(unlocked, workdir):
    invoke("set", "TOKEN", "valor-repetido", "-p", "A")
    result = invoke("set", "TOKEN", "valor-repetido", "-p", "B")
    assert "A.dev.TOKEN" in result.output


def test_link_and_run(unlocked, workdir, tmp_path):
    assert invoke("link", "-e", "prod").exit_code == 0
    assert find_link(workdir).project == "HPBot"
    invoke("set", "MONGO", "mongodb://db", "--shared")
    invoke("set", "TOKEN", "tok")
    invoke("set", "DB", "${compartidos.MONGO}")
    out = tmp_path / "env.txt"
    script = f"import os; open(r'{out}', 'w').write(os.environ['TOKEN'] + '|' + os.environ['DB'])"
    result = invoke("run", "--", sys.executable, "-c", script)
    assert result.exit_code == 0, result.output
    assert out.read_text() == "tok|mongodb://db"
    data = data_of(VaultFile())
    assert str(workdir) in data.projects["HPBot"].paths


def test_run_returns_child_exit_code(unlocked, workdir):
    invoke("link")
    result = invoke("run", "--", sys.executable, "-c", "raise SystemExit(3)")
    assert result.exit_code == 3


def test_run_errors(unlocked, workdir):
    invoke("link")
    assert invoke("run").exit_code == 1
    assert invoke("run", "--", "comando-que-no-existe-xyz").exit_code == 1


def test_link_refuses_to_change_without_force(unlocked, workdir):
    invoke("link")
    assert invoke("link", "Otro").exit_code == 1
    assert invoke("link", "Otro", "--force").exit_code == 0
    assert find_link(workdir).project == "Otro"
    assert invoke("unlink").exit_code == 0
    assert not (workdir / LINK_FILE).exists()


def test_pull_and_example(unlocked, workdir):
    invoke("link")
    invoke("set", "TOKEN", "tok con espacios", "--note", "Token del bot")
    make_repo(workdir)
    result = invoke("pull")
    assert result.exit_code == 0
    assert dotenv.parse((workdir / ".env").read_text(encoding="utf-8")) == {"TOKEN": "tok con espacios"}
    assert ".env" in (workdir / ".gitignore").read_text()
    assert "Añadido" in result.output
    assert "Añadido" not in invoke("pull").output  # ya estaba ignorado
    (workdir / ".env").write_text("OTRO=1\n", encoding="utf-8")
    assert invoke("pull", input="n\n").exit_code == 1
    assert invoke("pull", "--force").exit_code == 0
    assert invoke("example").exit_code == 0
    text = (workdir / ".env.example").read_text(encoding="utf-8")
    assert "# Token del bot\nTOKEN=\n" in text and "tok" not in text.replace("Token", "")


def test_import(unlocked, tmp_path):
    root = tmp_path / "proyectos"
    (root / "HPBot").mkdir(parents=True)
    (root / "HPBot" / ".env").write_text(f"DISCORD_TOKEN={DISCORD}\n", encoding="utf-8")
    result = invoke("import", str(root), "--dry-run")
    assert "HPBot" in result.output and not data_of(VaultFile()).projects
    result = invoke("import", str(root), "--link")
    assert result.exit_code == 0 and "1 nuevas" in result.output
    assert data_of(VaultFile()).get(Location("HPBot", "dev", "DISCORD_TOKEN")).value == DISCORD
    assert find_link(root / "HPBot").project == "HPBot"
    (root / "HPBot" / ".env").write_text("DISCORD_TOKEN=otro\n", encoding="utf-8")
    result = invoke("import", str(root))
    assert "valor distinto" in result.output
    assert invoke("import", str(tmp_path / "no-existe")).exit_code == 1


def test_rm_respects_references(unlocked, workdir):
    invoke("set", "MONGO", "x", "--shared")
    invoke("set", "DB", "${compartidos.MONGO}", "-p", "HPBot")
    result = invoke("rm", "MONGO", "--shared")
    assert result.exit_code == 1 and "HPBot.dev.DB" in result.output
    assert invoke("rm", "MONGO", "--shared", "--force").exit_code == 0
    assert invoke("rm", "MONGO", "--shared").exit_code == 1


def test_rotate_updates_every_copy(unlocked, workdir):
    invoke("set", "TOKEN", "viejo-token", "-p", "A")
    invoke("set", "BOT_TOKEN", "viejo-token", "-p", "B", "-e", "prod")
    invoke("set", "REF", "${A.dev.TOKEN}", "-p", "C")
    result = invoke("rotate", "TOKEN", "-p", "A", input="nuevo-token\nnuevo-token\n")
    assert result.exit_code == 0, result.output
    assert "C.dev.REF" in result.output
    data = data_of(VaultFile())
    assert data.get(Location("B", "prod", "BOT_TOKEN")).value == "nuevo-token"
    assert data.resolve_value(Location("C", "dev", "REF")) == "nuevo-token"
    assert invoke("rotate", "REF", "-p", "C").exit_code == 1  # es una referencia


def test_drop(unlocked, workdir):
    invoke("set", "X", "1", "-p", "A", "-e", "prod")
    invoke("set", "Y", "1", "-p", "A")
    invoke("set", "Z", "${A.dev.Y}", "-p", "B")
    assert invoke("drop", "A", "-y").exit_code == 1  # B depende de A
    assert invoke("drop", "A", "-e", "prod", "-y").exit_code == 0
    assert set(data_of(VaultFile()).projects["A"].envs) == {"dev"}
    invoke("rm", "Z", "-p", "B")
    assert invoke("drop", "A", input="n\n").exit_code == 1
    assert invoke("drop", "A", input="s\n").exit_code == 0 or invoke("drop", "A", "-y").exit_code == 0
    assert "A" not in data_of(VaultFile()).projects


def test_lock_unlock_status(unlocked, session, workdir):
    file = VaultFile()
    assert "abierta" in invoke("status").output
    invoke("lock")
    assert session.load(file.id) is None
    assert "bloqueada" in invoke("status").output
    result = invoke("ls", input="mala\n" + f"{PASSWORD}\n")
    assert result.exit_code == 0 and "Contraseña incorrecta" in result.output
    assert session.load(file.id) is not None  # queda abierta tras escribirla
    invoke("lock")
    assert invoke("unlock", "-m", "5", input=f"{PASSWORD}\n").exit_code == 0
    assert 0 < session.remaining(file.id) <= 300


def test_three_wrong_passwords(vault_file):
    result = invoke("ls", input="a\nb\nc\n")
    assert result.exit_code == 1 and "incorrecta" in result.output


def test_env_password(vault_file, session, monkeypatch):
    monkeypatch.setenv("ENVVAULT_PASSWORD", PASSWORD)
    assert invoke("set", "A", "1", "--shared").exit_code == 0
    assert session.load(vault_file.id) is None  # con la variable no se crea sesión


def test_passwd_and_recover(vault_file, session):
    result = invoke("passwd", input=f"{PASSWORD}\nnueva-clave-1\nnueva-clave-1\n")
    assert result.exit_code == 0, result.output
    assert VaultFile().unlock("nueva-clave-1")
    code = invoke("recovery-key", input="nueva-clave-1\n").output
    recovery = next(line.strip(" │|") for line in code.splitlines() if line.count("-") == 7)
    result = invoke("recover", input=f"{recovery}\notra-clave-22\notra-clave-22\n")
    assert result.exit_code == 0, result.output
    assert VaultFile().unlock("otra-clave-22")


def test_scan_command(unlocked, tmp_path, monkeypatch):
    monkeypatch.setattr("envvault.scan.git_available", lambda: False)
    code = tmp_path / "bot"
    code.mkdir()
    (code / "index.js").write_text(f'client.login("{DISCORD}")', encoding="utf-8")
    invoke("set", "TOKEN", DISCORD, "-p", "HPBot")
    result = invoke("scan", str(code))
    assert result.exit_code == 1
    assert "index.js:1" in result.output and "HPBot.dev.TOKEN" in result.output
    (code / "index.js").write_text("client.login(process.env.TOKEN)", encoding="utf-8")
    result = invoke("scan", str(code))
    assert result.exit_code == 0 and "Nada sospechoso" in result.output


def test_scan_all_projects_with_history(unlocked, tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "bot")
    (repo / "a.js").write_text(f'"{DISCORD}"', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "x")
    (repo / "a.js").write_text("", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "limpio")
    monkeypatch.chdir(repo)
    invoke("link")
    result = invoke("scan", "--all", "--history")
    assert result.exit_code == 1
    assert "a.js @" in result.output and "historial" in result.output


def test_check_command(unlocked, monkeypatch):
    from envvault.check import CheckResult

    invoke("set", "TOKEN", DISCORD, "-p", "HPBot")
    invoke("set", "OTRO", "no-es-token", "-p", "HPBot")
    monkeypatch.setattr(cli, "check_value", lambda client, value: CheckResult("inválido", "HTTP 401"))
    result = invoke("check")
    assert result.exit_code == 1
    assert "HPBot.dev.TOKEN" in result.output and "OTRO" not in result.output
    monkeypatch.setattr(cli, "check_value", lambda client, value: CheckResult("válido", "HPBot#1"))
    assert invoke("check", "hpbot").exit_code == 0
    assert invoke("check", "NoExiste").exit_code == 1


def test_locked_vault_non_interactive(vault_file):
    with pytest.raises(VaultLocked):
        cli.open_vault(interactive=False)
