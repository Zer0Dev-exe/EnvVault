"""Línea de comandos de EnvVault (Typer)."""

from __future__ import annotations

import functools
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Callable, Optional

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from envvault import __version__, clipboard, dotenv, gitutil, importer, runner
from envvault.check import INVALID, VALID, check_value, can_check
from envvault.errors import EnvVaultError, VaultLocked, WrongPassword
from envvault.linkfile import LINK_FILE, find_link, read_link, write_link
from envvault.model import DEFAULT_ENV, SHARED, Location, VaultData, sanitize_name
from envvault.patterns import describe, detect_kind, mask
from envvault.scan import Finding, Scanner
from envvault.session import KeyringSession, SessionStore, timeout_minutes
from envvault.store import VaultFile
from envvault.vault import Vault

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="envvault",
    help="Bóveda cifrada para los .env y tokens de todos tus proyectos.",
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode="rich",
)

ProjectOpt = Annotated[Optional[str], typer.Option("--project", "-p", help="Proyecto (por defecto, el enlazado en esta carpeta).")]
EnvOpt = Annotated[Optional[str], typer.Option("--env", "-e", help="Entorno: dev, prod… (por defecto, el del enlace o dev).")]
SharedOpt = Annotated[bool, typer.Option("--shared", "-s", help="Usar los secretos compartidos.")]
MIN_PASSWORD = 8


# ---------------------------------------------------------------------------
# Infraestructura (los tests sustituyen vault_file y session_store)
# ---------------------------------------------------------------------------
def vault_file() -> VaultFile:
    return VaultFile()


def session_store() -> SessionStore:
    return KeyringSession()


def handle_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except EnvVaultError as exc:
            err_console.print(f"[bold red]Error:[/] {escape(str(exc))}")
            raise typer.Exit(1) from exc
        except (KeyboardInterrupt, typer.Abort):
            err_console.print("\n[yellow]Cancelado.[/]")
            raise typer.Exit(130) from None

    return wrapper


def prompt_password(label: str = "🔐 Contraseña maestra") -> str:
    return typer.prompt(label, hide_input=True)


def prompt_new_password() -> str:
    for _ in range(3):
        password = typer.prompt("Nueva contraseña maestra", hide_input=True,
                                confirmation_prompt="Repítela")
        if len(password) >= MIN_PASSWORD:
            return password
        err_console.print(f"[yellow]Tiene que tener al menos {MIN_PASSWORD} caracteres.[/]")
    raise EnvVaultError("Demasiados intentos.")


def store_session(file: VaultFile, key: bytes, minutes: float) -> None:
    if not session_store().store(file.id, key, minutes):
        err_console.print("[yellow]No se puede guardar la sesión en el llavero del sistema: "
                          "cada comando te pedirá la contraseña.[/]")


def open_vault(interactive: bool = True) -> Vault:
    """Abre la bóveda con la sesión activa, ENVVAULT_PASSWORD o pidiendo la contraseña."""
    file = vault_file()
    file.header()
    session = session_store()
    key = session.load(file.id)
    if key is not None:
        try:
            return Vault(file, key, file.load(key))
        except VaultLocked:
            session.clear(file.id)
    env_password = os.environ.get("ENVVAULT_PASSWORD")
    if env_password is not None:
        key = file.unlock(env_password)
        return Vault(file, key, file.load(key))
    if not interactive:
        raise VaultLocked("La bóveda está bloqueada. Ejecuta `envvault unlock`.")
    for attempt in range(3):
        try:
            password = prompt_password()
            with console.status("Abriendo la bóveda…"):
                key = file.unlock(password)
            break
        except WrongPassword:
            if attempt == 2:
                raise
            err_console.print("[red]Contraseña incorrecta.[/]")
    data = file.load(key)
    store_session(file, key, timeout_minutes())
    return Vault(file, key, data)


def resolve_scope(project: str | None, env: str | None, shared: bool = False) -> tuple[str | None, str | None]:
    if shared:
        return None, None
    if project is None:
        link = find_link()
        if link is None:
            raise EnvVaultError(
                "Esta carpeta no está enlazada con ningún proyecto. Usa `envvault link`, "
                "o indica -p PROYECTO (o --shared para los compartidos)."
            )
        project, env = link.project, env or link.env
    return project, env or DEFAULT_ENV


def location(data: VaultData, key: str, project: str | None, env: str | None, shared: bool) -> Location:
    project, env = resolve_scope(project, env, shared)
    return data.canonical(Location(project, env, key))


def display_value(value: str, is_reference: bool) -> str:
    return f"[cyan]{escape(value)}[/]" if is_reference else mask(value)


def minutes_text(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


# ---------------------------------------------------------------------------
# Bóveda
# ---------------------------------------------------------------------------
@app.command()
@handle_errors
def init() -> None:
    """Crea la bóveda y te da la clave de recuperación."""
    file = vault_file()
    if file.exists():
        raise EnvVaultError(f"Ya tienes una bóveda en {file.path}.")
    console.print("Vas a crear tu bóveda. La contraseña maestra la cifra: [b]no se puede recuperar sin ella[/] "
                  "(salvo con la clave de recuperación que verás ahora).")
    password = prompt_new_password()
    with console.status("Creando la bóveda…"):
        key, code = file.create(password)
    store_session(file, key, timeout_minutes())
    console.print(f"[green]✓[/] Bóveda creada en {file.path}")
    console.print(Panel(
        f"[bold]{code}[/]\n\nApúntala en papel y guárdala. Es la única forma de entrar si olvidas la "
        "contraseña.\n[dim]No se vuelve a mostrar.[/]",
        title="🔑 Clave de recuperación", border_style="yellow", expand=False,
    ))
    console.print("Siguiente paso: [b]envvault import ~/proyectos[/] o, dentro de un proyecto, [b]envvault link[/].")


@app.command()
@handle_errors
def unlock(minutes: Annotated[Optional[int], typer.Option("--minutes", "-m", help="Minutos que queda abierta.")] = None) -> None:
    """Abre la bóveda durante un rato (15 min por defecto)."""
    file = vault_file()
    file.header()
    minutes = minutes or timeout_minutes()
    session = session_store()
    key = session.load(file.id)
    if key is None:
        key = file.unlock(prompt_password())
    file.load(key)
    store_session(file, key, minutes)
    console.print(f"🔓 Bóveda abierta durante {minutes} min.")


@app.command()
@handle_errors
def lock() -> None:
    """Cierra la bóveda ya."""
    file = vault_file()
    file.header()
    session_store().clear(file.id)
    console.print("🔒 Bóveda bloqueada.")


@app.command()
@handle_errors
def status() -> None:
    """Dónde está la bóveda, si está abierta y qué proyecto hay enlazado aquí."""
    file = vault_file()
    table = Table.grid(padding=(0, 2))
    table.add_row("[b]Bóveda[/]", str(file.path))
    if not file.exists():
        table.add_row("[b]Estado[/]", "[yellow]no existe[/] (envvault init)")
        console.print(table)
        return
    remaining = session_store().remaining(file.id)
    state = f"[green]🔓 abierta[/] (se bloquea en {minutes_text(remaining)})" if remaining else "[yellow]🔒 bloqueada[/]"
    table.add_row("[b]Estado[/]", state)
    link = find_link()
    if link:
        table.add_row("[b]Aquí[/]", f"{link.project} · {link.env}  [dim]({link.path})[/]")
    else:
        table.add_row("[b]Aquí[/]", "[dim]carpeta sin enlazar[/]")
    if remaining:
        vault = open_vault(interactive=False)
        total = sum(1 for _ in vault.data.iter_secrets())
        table.add_row("[b]Contenido[/]", f"{len(vault.data.projects)} proyectos · {len(vault.data.shared)} compartidos · {total} secretos")
    console.print(table)


@app.command()
@handle_errors
def passwd() -> None:
    """Cambia la contraseña maestra."""
    file = vault_file()
    file.header()
    key = file.unlock(prompt_password("Contraseña actual"))
    password = prompt_new_password()
    with console.status("Guardando…"):
        file.change_password(key, password)
    store_session(file, key, timeout_minutes())
    console.print("[green]✓[/] Contraseña cambiada. La clave de recuperación sigue siendo la misma.")


@app.command()
@handle_errors
def recover() -> None:
    """Pon una contraseña nueva usando la clave de recuperación."""
    file = vault_file()
    file.header()
    key = file.unlock_with_recovery(typer.prompt("Clave de recuperación"))
    password = prompt_new_password()
    with console.status("Guardando…"):
        file.change_password(key, password)
    store_session(file, key, timeout_minutes())
    console.print("[green]✓[/] Contraseña nueva guardada. Si crees que alguien ha visto la clave de recuperación, "
                  "genera otra con [b]envvault recovery-key[/].")


@app.command("recovery-key")
@handle_errors
def recovery_key() -> None:
    """Genera una clave de recuperación nueva (la anterior deja de valer)."""
    file = vault_file()
    file.header()
    key = file.unlock(prompt_password())
    code = file.new_recovery_code(key)
    console.print(Panel(f"[bold]{code}[/]\n\nLa anterior ya no sirve.", title="🔑 Clave de recuperación nueva",
                        border_style="yellow", expand=False))


# ---------------------------------------------------------------------------
# Secretos
# ---------------------------------------------------------------------------
@app.command("set")
@handle_errors
def set_(
    key: Annotated[str, typer.Argument(help="Nombre de la variable (o CLAVE=valor).")],
    value: Annotated[Optional[str], typer.Argument(help="Valor. Si lo omites se pide sin mostrarlo (recomendado).")] = None,
    project: ProjectOpt = None,
    env: EnvOpt = None,
    shared: SharedOpt = False,
    note: Annotated[Optional[str], typer.Option("--note", "-n", help="Nota: para qué es.")] = None,
    expires: Annotated[Optional[str], typer.Option(help="Fecha de caducidad (AAAA-MM-DD).")] = None,
) -> None:
    """Guarda un secreto. Ejemplo: envvault set DISCORD_TOKEN"""
    if value is None and "=" in key:
        key, value = key.split("=", 1)
    if expires:
        try:
            date.fromisoformat(expires)
        except ValueError as exc:
            raise EnvVaultError("La caducidad va en formato AAAA-MM-DD.") from exc
    vault = open_vault()
    loc = location(vault.data, key, project, env, shared)
    if value is None:
        value = (sys.stdin.read().rstrip("\r\n") if not sys.stdin.isatty()
                 else typer.prompt(f"Valor de {loc}", hide_input=True))
    elsewhere = [str(other) for other in vault.data.find_value(value) if other != loc]
    vault.data.set(loc, value, note=note, expires=expires)
    vault.save()
    kind = detect_kind(value)
    extra = f" [dim]({kind.label})[/]" if kind else ""
    console.print(f"[green]✓[/] {loc} guardado{extra}")
    if elsewhere:
        console.print(f"[dim]El mismo valor está también en {', '.join(elsewhere)}. Puedes guardarlo una vez en "
                      f"compartidos y usar ${{{SHARED}.{loc.key}}} en cada proyecto.[/]")


@app.command()
@handle_errors
def get(
    key: str,
    project: ProjectOpt = None,
    env: EnvOpt = None,
    shared: SharedOpt = False,
    show: Annotated[bool, typer.Option("--show", help="Mostrarlo en pantalla en vez de copiarlo.")] = False,
    raw: Annotated[bool, typer.Option("--raw", help="Solo el valor, para scripts.")] = False,
    seconds: Annotated[int, typer.Option("--clear", help="Segundos hasta borrar el portapapeles.")] = 30,
) -> None:
    """Copia un secreto al portapapeles (se borra a los 30 s)."""
    vault = open_vault()
    loc = location(vault.data, key, project, env, shared)
    value = vault.data.resolve_value(loc)
    if raw:
        typer.echo(value)
    elif show:
        console.print(escape(value), highlight=False)
    else:
        clipboard.copy_temporarily(value, seconds)
        console.print(f"📋 {loc} copiado. Se borra del portapapeles en {seconds} s.")


@app.command()
@handle_errors
def rm(
    key: str,
    project: ProjectOpt = None,
    env: EnvOpt = None,
    shared: SharedOpt = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Borrarlo aunque otros lo referencien.")] = False,
) -> None:
    """Borra un secreto."""
    vault = open_vault()
    loc = location(vault.data, key, project, env, shared)
    vault.data.get(loc)
    users = vault.data.referrers(loc)
    if users and not force:
        raise EnvVaultError(f"{loc} se usa en: {', '.join(map(str, users))}. Usa --force para borrarlo igualmente.")
    vault.data.remove(loc)
    vault.save()
    console.print(f"[green]✓[/] {loc} borrado.")


@app.command("ls")
@handle_errors
def ls(
    project: Annotated[Optional[str], typer.Argument(help="Proyecto a detallar.")] = None,
    shared: SharedOpt = False,
) -> None:
    """Lista proyectos, o los secretos de uno (enmascarados)."""
    vault = open_vault()
    data = vault.data
    if shared:
        _print_scope(data, None, None)
        return
    if project is None:
        table = Table(title="🔐 EnvVault", title_justify="left")
        table.add_column("Proyecto", style="bold")
        table.add_column("Entornos")
        table.add_column("Secretos", justify="right")
        table.add_column("Carpetas", style="dim")
        table.add_row(f"🌐 {SHARED}", "—", str(len(data.shared)), "")
        for proj in sorted(data.projects.values(), key=lambda p: p.name.lower()):
            table.add_row(proj.name, ", ".join(proj.envs) or "—", str(proj.count()),
                          "\n".join(proj.paths) if proj.paths else "")
        console.print(table)
        return
    proj = data.project(project)
    if not proj.envs:
        console.print(f"[dim]{proj.name} no tiene secretos todavía.[/]")
    for env_name in proj.envs:
        _print_scope(data, proj.name, env_name)


def _print_scope(data: VaultData, project: str | None, env: str | None) -> None:
    scope = data.scope(project, env)
    title = f"🌐 {SHARED}" if project is None else f"{project} · {env}"
    table = Table(title=title, title_justify="left")
    table.add_column("Clave", style="bold")
    table.add_column("Valor")
    table.add_column("Tipo", style="dim")
    table.add_column("Nota")
    table.add_column("Actualizado", style="dim")
    today = date.today().isoformat()
    for key, secret in sorted(scope.items()):
        described = describe(secret.value, key)
        note = escape(secret.note)
        if secret.expires:
            style = "red" if secret.expires < today else "yellow"
            note = f"{note} [{style}](caduca {secret.expires})[/]".strip()
        table.add_row(key, display_value(secret.value, secret.is_reference), described[0] if described else "",
                      note, secret.updated_at[:10])
    if not scope:
        table.add_row("[dim]vacío[/]", "", "", "", "")
    console.print(table)


@app.command()
@handle_errors
def rotate(
    key: str,
    project: ProjectOpt = None,
    env: EnvOpt = None,
    shared: SharedOpt = False,
) -> None:
    """Cambia un token y lo actualiza en todos los proyectos que tienen el mismo valor."""
    vault = open_vault()
    loc = location(vault.data, key, project, env, shared)
    secret = vault.data.get(loc)
    if secret.is_reference:
        targets = ", ".join(map(str, vault.data.references(loc)))
        raise EnvVaultError(f"{loc} es una referencia a {targets}: rota ese.")
    places = vault.data.find_value(secret.value)
    users = vault.data.referrers(loc)
    console.print(f"Se actualizará en {len(places)} sitio(s):")
    for place in places:
        console.print(f"  • {place}")
    for user in users:
        console.print(f"  • {user} [dim](referencia, se actualiza sola)[/]")
    new = typer.prompt("Valor nuevo", hide_input=True, confirmation_prompt="Repítelo")
    if new == secret.value:
        raise EnvVaultError("El valor nuevo es igual que el actual.")
    for place in places:
        vault.data.set(place, new)
    vault.save()
    console.print(f"[green]✓[/] Rotado en {len(places)} sitio(s). Reinicia los procesos que usen el valor antiguo; "
                  "comprueba el nuevo con [b]envvault check[/].")


@app.command()
@handle_errors
def drop(
    project: str,
    env: EnvOpt = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="No pedir confirmación.")] = False,
) -> None:
    """Borra un proyecto entero (o solo uno de sus entornos con -e)."""
    vault = open_vault()
    proj = vault.data.project(project)
    if env is not None:
        vault.data.scope(proj.name, env)
    what = f"el entorno {env} de {proj.name}" if env else f"el proyecto {proj.name}"
    inside = [loc for loc, _ in vault.data.iter_secrets()
              if loc.project == proj.name and (env is None or loc.env == env)]
    outside_users = {str(user) for loc in inside for user in vault.data.referrers(loc) if user not in inside}
    if outside_users:
        raise EnvVaultError(f"Otros secretos usan {what}: {', '.join(sorted(outside_users))}.")
    if not yes and not typer.confirm(f"¿Borrar {what} ({len(inside)} secretos)?"):
        raise typer.Exit(1)
    if env:
        del proj.envs[env]
    else:
        vault.data.remove_project(proj.name)
    vault.save()
    console.print(f"[green]✓[/] Borrado {what}.")


# ---------------------------------------------------------------------------
# Proyectos y carpetas
# ---------------------------------------------------------------------------
@app.command("import")
@handle_errors
def import_(
    path: Annotated[Path, typer.Argument(help="Carpeta donde buscar (se recorre entera).")] = Path("."),
    dry_run: Annotated[bool, typer.Option("--dry-run", "-d", help="Solo mostrar qué se importaría.")] = False,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Pisar valores distintos ya guardados.")] = False,
    json_files: Annotated[bool, typer.Option("--json/--no-json", help="Importar también config.json con tokens.")] = True,
    link: Annotated[bool, typer.Option("--link", help="Enlazar cada carpeta con su proyecto (.envvault.toml).")] = False,
) -> None:
    """Busca los .env de tus proyectos y los mete en la bóveda."""
    if not path.is_dir():
        raise EnvVaultError(f"{path} no es una carpeta.")
    with console.status("Buscando ficheros .env…"):
        founds = importer.discover(path, include_json=json_files)
    if not founds:
        console.print("No se ha encontrado ningún .env con variables.")
        return
    root = path.resolve()
    table = Table(title=f"Encontrado en {root}", title_justify="left")
    table.add_column("Proyecto", style="bold")
    table.add_column("Entorno")
    table.add_column("Fichero", style="dim")
    table.add_column("Variables", justify="right")
    for found in founds:
        table.add_row(found.project, found.env, _relative(found.path, root), str(len(found.values)))
    console.print(table)
    if dry_run:
        return
    vault = open_vault()
    report = importer.apply(vault.data, founds, overwrite=overwrite)
    vault.save()
    console.print(f"[green]✓[/] {len(report.added)} nuevas · {len(report.updated)} actualizadas · "
                  f"{len(report.unchanged)} iguales")
    if report.conflicts:
        console.print(f"[yellow]{len(report.conflicts)} con un valor distinto al guardado (no se han tocado; "
                      "usa --overwrite para pisarlas):[/]")
        for loc, file in report.conflicts:
            console.print(f"  • {loc}  [dim]{_relative(file, root)}[/]")
    if link:
        linked = 0
        for found in founds:
            folder = found.path.parent
            if not (folder / LINK_FILE).exists():
                write_link(folder, vault.data.project(found.project).name, found.env)
                linked += 1
        console.print(f"[green]✓[/] {linked} carpeta(s) enlazadas.")
    else:
        console.print("[dim]Enlaza cada carpeta con [b]envvault link[/] (o repite con --link) y arranca con "
                      "[b]envvault run -- <comando>[/]. Después puedes borrar los .env.[/]")
    if any(f.kind == "json" for f in founds):
        console.print("[dim]Ojo: los config.json se leen desde el código. Cambia p. ej. "
                      "require('./config.json').token por process.env.TOKEN para usar la bóveda.[/]")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


@app.command("link")
@handle_errors
def link_(
    project: Annotated[Optional[str], typer.Argument(help="Proyecto (por defecto, el nombre de la carpeta).")] = None,
    env: Annotated[str, typer.Option("--env", "-e", help="Entorno que usará esta carpeta.")] = DEFAULT_ENV,
    force: Annotated[bool, typer.Option("--force", "-f", help="Sustituir un enlace existente.")] = False,
) -> None:
    """Enlaza la carpeta actual con un proyecto de la bóveda."""
    folder = Path.cwd()
    existing = folder / LINK_FILE
    if existing.is_file() and not force:
        current = read_link(existing)
        if current.project.lower() != (project or current.project).lower() or current.env != env:
            raise EnvVaultError(f"Esta carpeta ya está enlazada con {current.project} · {current.env}. Usa --force.")
    vault = open_vault()
    name = project or sanitize_name(folder.name)
    proj = vault.data.ensure_project(name)
    vault.data.scope(proj.name, env, create=True)
    proj.add_path(str(folder))
    vault.save()
    write_link(folder, proj.name, env)
    console.print(f"[green]✓[/] {folder.name} → {proj.name} · {env}  [dim]({LINK_FILE}, se puede subir a git)[/]")
    if not proj.envs.get(env) and any(importer.is_env_file(p.name) for p in folder.iterdir() if p.is_file()):
        console.print("Hay un .env en esta carpeta: impórtalo con [b]envvault import .[/]")


@app.command()
@handle_errors
def unlink() -> None:
    """Quita el enlace de la carpeta actual (la bóveda no se toca)."""
    link = find_link()
    if link is None:
        raise EnvVaultError("Esta carpeta no está enlazada.")
    link.path.unlink()
    console.print(f"[green]✓[/] Enlace con {link.project} eliminado ({link.path}).")


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@handle_errors
def run(
    ctx: typer.Context,
    project: ProjectOpt = None,
    env: EnvOpt = None,
    keep_existing: Annotated[bool, typer.Option("--keep-existing", help="Si una variable ya existe en el entorno, no la pisa.")] = False,
) -> None:
    """Ejecuta un comando con las variables de la bóveda: envvault run -- node index.js"""
    command = list(ctx.args)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise EnvVaultError("Falta el comando. Ejemplo: envvault run -- node index.js")
    project, env = resolve_scope(project, env)
    vault = open_vault()
    values = vault.data.resolve(project, env)
    err_console.print(f"[dim]🔐 {len(values)} variables de {vault.data.project(project).name} · {env}[/]")
    code = runner.run_command(command, runner.build_env(values, override=not keep_existing))
    raise typer.Exit(code)


@app.command()
@handle_errors
def pull(
    project: ProjectOpt = None,
    env: EnvOpt = None,
    output: Annotated[Path, typer.Option("--output", "-o", help="Fichero a escribir.")] = Path(".env"),
    force: Annotated[bool, typer.Option("--force", "-f", help="Sobrescribir sin preguntar.")] = False,
) -> None:
    """Escribe el .env en disco (mejor usa `run`, que no deja ficheros)."""
    project, env = resolve_scope(project, env)
    vault = open_vault()
    name = vault.data.project(project).name
    values = vault.data.resolve(name, env)
    text = dotenv.dump(values, header=f"Generado por EnvVault ({name} · {env}). No lo subas a git.",
                       notes={k: s.note for k, s in vault.data.scope(name, env).items() if s.note})
    if output.exists() and output.read_text(encoding="utf-8", errors="replace") != text and not force:
        if not typer.confirm(f"{output} ya existe y es distinto. ¿Sobrescribirlo?"):
            raise typer.Exit(1)
    output.write_text(text, encoding="utf-8")
    console.print(f"[green]✓[/] {output} escrito con {len(values)} variables.")
    if gitutil.ensure_ignored(output.resolve()):
        console.print(f"[green]✓[/] Añadido {output.name} al .gitignore.")


@app.command()
@handle_errors
def example(
    project: ProjectOpt = None,
    env: EnvOpt = None,
    output: Annotated[Path, typer.Option("--output", "-o", help="Fichero a escribir.")] = Path(".env.example"),
) -> None:
    """Genera un .env.example con las claves y sin valores."""
    project, env = resolve_scope(project, env)
    vault = open_vault()
    name = vault.data.project(project).name
    scope = vault.data.scope(name, env)
    text = dotenv.dump({key: "" for key in scope}, header="Variables que necesita este proyecto. Rellénalas en tu .env.",
                       notes={k: s.note for k, s in scope.items() if s.note})
    output.write_text(text, encoding="utf-8")
    console.print(f"[green]✓[/] {output} escrito con {len(scope)} claves.")


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------
@app.command()
@handle_errors
def scan(
    path: Annotated[Optional[Path], typer.Argument(help="Carpeta a revisar (por defecto, la actual).")] = None,
    history: Annotated[bool, typer.Option("--history", "-H", help="Revisar también todo el historial de git.")] = False,
    all_projects: Annotated[bool, typer.Option("--all", "-a", help="Revisar las carpetas de todos los proyectos de la bóveda.")] = False,
) -> None:
    """Busca tokens filtrados en tus carpetas (y en el historial de git con -H)."""
    vault: Vault | None
    if all_projects:
        vault = open_vault()
        roots = sorted({Path(p) for proj in vault.data.projects.values() for p in proj.paths if Path(p).is_dir()})
        if not roots:
            raise EnvVaultError("Ningún proyecto tiene carpetas enlazadas (usa `envvault link` o `import`).")
    else:
        roots = [path or Path(".")]
        try:
            vault = open_vault(interactive=False) if vault_file().exists() else None
        except EnvVaultError:
            vault = None
    if roots[0] and not roots[0].is_dir():
        raise EnvVaultError(f"{roots[0]} no es una carpeta.")
    scanner = Scanner(vault.secret_values() if vault else None)
    findings: list[Finding] = []
    files = 0
    with console.status("Revisando…") as status_line:
        for root in roots:
            status_line.update(f"Revisando {root}…")
            result = scanner.scan_tree(root)
            files += result.files
            label = root.resolve().name
            for finding in result.findings:
                if len(roots) > 1:
                    finding.path = f"{label}/{finding.path}"
                findings.append(finding)
            if history:
                for repo in result.repos:
                    status_line.update(f"Revisando el historial de {repo.name}…")
                    for finding in scanner.scan_history(repo, root.resolve()):
                        if len(roots) > 1:
                            finding.path = f"{label}/{finding.path}"
                        findings.append(finding)
    if vault is None:
        console.print("[dim]Bóveda bloqueada: no se buscan sus valores literales (ejecuta `envvault unlock` antes).[/]")
    if not findings:
        console.print(f"[green]✓ Nada sospechoso[/] en {files} ficheros{' ni en el historial' if history else ''}.")
        return
    table = Table(title=f"⚠ {len(findings)} hallazgos en {files} ficheros", title_justify="left")
    table.add_column("Qué", style="bold")
    table.add_column("Dónde")
    table.add_column("Valor", style="dim")
    table.add_column("En la bóveda como", style="cyan")
    for f in sorted(findings, key=lambda f: (f.path, f.line or 0)):
        table.add_row(escape(f.label), escape(f.where), f.masked, "\n".join(f.vault))
    console.print(table)
    if any(f.commit for f in findings):
        console.print("[yellow]Lo que está en el historial sigue ahí aunque borres el fichero: rota esos tokens "
                      "(envvault rotate) y, si el repo es público, considera reescribir el historial.[/]")
    raise typer.Exit(1)


@app.command()
@handle_errors
def check(
    project: Annotated[Optional[str], typer.Argument(help="Solo este proyecto.")] = None,
    shared: SharedOpt = False,
) -> None:
    """Comprueba si los tokens de la bóveda siguen siendo válidos."""
    vault = open_vault()
    data = vault.data
    selected = [
        (loc, secret) for loc, secret in data.iter_secrets()
        if not secret.is_reference and can_check(secret.value)
        and (not shared or loc.project is None)
        and (project is None or (loc.project or "").lower() == project.lower())
    ]
    if project is not None:
        data.project(project)
    if not selected:
        console.print("No hay tokens que se sepan comprobar (Discord, GitHub, OpenAI, Anthropic, Google, Telegram).")
        return
    table = Table(title="Estado de los tokens", title_justify="left")
    table.add_column("Secreto", style="bold")
    table.add_column("Tipo", style="dim")
    table.add_column("Estado")
    table.add_column("Detalle")
    results: dict[str, Any] = {}
    invalid = 0
    with httpx.Client(timeout=10, follow_redirects=False) as client, console.status("Comprobando…"):
        for loc, secret in selected:
            if secret.value not in results:
                results[secret.value] = check_value(client, secret.value)
            result = results[secret.value]
            style = {VALID: "green", INVALID: "red"}.get(result.status, "yellow")
            invalid += result.status == INVALID
            kind = detect_kind(secret.value)
            table.add_row(str(loc), kind.label if kind else "", f"[{style}]{result.status}[/]", escape(result.detail))
    console.print(table)
    console.print("[dim]Cada token solo se ha enviado al servicio que lo emitió.[/]")
    if invalid:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# TUI y arranque
# ---------------------------------------------------------------------------
@app.command()
@handle_errors
def tui() -> None:
    """Interfaz interactiva."""
    from envvault.tui import EnvVaultApp

    vault = open_vault()
    session = session_store()
    remaining = session.remaining(vault.file.id)
    lock_at = time.time() + (remaining if remaining else timeout_minutes() * 60)
    result = EnvVaultApp(vault, lock_at=lock_at, on_lock=lambda: session.clear(vault.file.id)).run()
    if result == "locked":
        console.print("🔒 Bóveda bloqueada.")
    elif result == "timeout":
        console.print("🔒 Bóveda bloqueada por tiempo.")


def _version(value: bool) -> None:
    if value:
        console.print(f"envvault {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True, help="Muestra la versión.")] = False,
) -> None:
    """Sin comando: abre la TUI (o te explica cómo empezar)."""
    if ctx.invoked_subcommand is not None:
        return
    if not vault_file().exists():
        console.print("🔐 [b]EnvVault[/]: aún no tienes bóveda. Créala con [b]envvault init[/] "
                      "(o mira [b]envvault --help[/]).")
        return
    tui()


def main() -> None:
    app()
