"""Interfaz interactiva (Textual)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Static, Tree

from envvault import clipboard
from envvault.errors import EnvVaultError
from envvault.model import KEY_RE, SHARED, Location
from envvault.patterns import CONFIG, SECRET, SERVICE, describe, detect_kind, mask
from envvault.scan import Finding, Scanner
from envvault.vault import Vault

EMERALD = "#10B981"
VALUE_WIDTH = 40  # el valor completo se ve en el panel de detalle
COLUMNS = ("CLAVE", "VALOR", "TIPO", "NOTA")
AMBER = "#F59E0B"
MUTED = "#6B7B8C"
MINT = "#A7F3D0"

THEME = Theme(
    name="envvault",
    primary=EMERALD,
    secondary=AMBER,
    accent="#22D3EE",
    success="#22C55E",
    warning=AMBER,
    error="#EF4444",
    foreground="#E5E7EB",
    background="#0A0F14",
    surface="#101820",
    panel="#15212B",
    dark=True,
)

CSS = """
Screen { background: $background; }

/* ------------------------------------------------------------ cabecera */
#top { height: 3; padding: 1 2; background: $panel; }
#brand { width: 1fr; }
#lock { width: auto; }

/* ------------------------------------------------------ barra lateral */
#main { height: 1fr; }
#sidebar { width: 28; background: $surface; padding: 1 1 0 1; }
.section-title { height: 1; padding: 0 1; color: $text-muted; text-style: bold; }
#scopes { background: transparent; padding: 0; margin-top: 1; scrollbar-size-vertical: 1; }
#scopes > .tree--guides { color: $panel-lighten-2; }
#scopes > .tree--guides-selected, #scopes > .tree--guides-hover { color: $primary; }
#scopes > .tree--cursor { background: $primary 20%; color: $text; text-style: none; }
#scopes:focus > .tree--cursor { background: $primary 35%; text-style: bold; }
#scopes > .tree--highlight-line { background: $boost; }

/* ------------------------------------------------------ zona principal */
#right { width: 1fr; padding: 1 2 0 2; }
#search { border: round $panel-lighten-2; background: transparent; padding: 0 1; }
#search:focus { border: round $primary; background: transparent; }
#search > .input--placeholder { color: $text-muted; }

.card { border: round $panel-lighten-2; background: transparent; padding: 0 1;
        border-title-color: $foreground; border-title-style: bold;
        border-subtitle-color: $text-muted; }
.card:focus-within { border: round $primary 70%; border-title-color: $primary; }
#table-card { height: 1fr; margin-top: 1; }
#secrets { height: 1fr; background: transparent; scrollbar-size-vertical: 1; }
#secrets > .datatable--header { background: $panel; color: $text-muted; text-style: bold; }
#secrets > .datatable--even-row { background: $boost; }
#secrets > .datatable--hover { background: $primary 10%; }
#secrets > .datatable--cursor { background: $primary 20%; color: $text; text-style: none; }
#secrets:focus > .datatable--cursor { background: $primary 35%; text-style: bold; }
#detail-card { height: auto; min-height: 5; max-height: 12; margin: 1 0; }
#detail { height: auto; padding: 0 1; }

/* --------------------------------------------------------------- pie */
Footer { background: $panel; }
Footer FooterKey .footer-key--key { color: $primary; background: transparent; text-style: bold; }
Footer FooterKey .footer-key--description { color: $text-muted; }

/* ----------------------------------------------------------- diálogos */
ModalScreen { align: center middle; background: $background 70%; }
.dialog { width: 72; height: auto; padding: 1 2; background: $surface; border: round $primary;
          border-title-color: $primary; border-title-style: bold; }
.dialog.wide { width: 110; }
.dialog.danger { width: 60; border: round $error; border-title-color: $error; }
.dialog Label { color: $text-muted; margin-top: 1; }
.dialog Input { border: round $panel-lighten-2; background: transparent; }
.dialog Input:focus { border: round $primary; background: transparent; }
.dialog Checkbox { background: transparent; border: none; padding: 0; margin-top: 1; }
.dialog-buttons { height: auto; margin-top: 1; align-horizontal: right; }
.dialog-buttons Button { margin-left: 2; min-width: 12; }
.error-text { color: $error; height: auto; }
#findings { height: auto; max-height: 20; margin-top: 1; background: transparent; }
"""

# Color de cada tipo de la columna «Tipo». Los servicios llevan su color de marca;
# lo que no esté aquí usa el color de su categoría (CATEGORY_COLORS).
KIND_COLORS = {
    # servicios
    "Discord": "#5865F2", "Webhook Discord": "#5865F2", "GitHub": "#E6EDF3", "GitLab": "#FC6D26",
    "Anthropic": "#D97757", "OpenAI": "#10A37F", "Google": "#4285F4", "Telegram": "#26A5E4",
    "AWS": "#FF9900", "Slack": "#E01E5A", "Webhook Slack": "#E01E5A", "Stripe": "#635BFF",
    "Stripe webhook": "#635BFF", "npm": "#CB3837", "PyPI": "#3775A9", "Hugging Face": "#FFD21E",
    "Groq": "#F55036", "xAI": "#E5E7EB", "Perplexity": "#20B8CD", "Replicate": "#E5E7EB",
    "SendGrid": "#1A82E2", "Mailgun": "#F06B66", "Twilio": "#F22F46", "Shopify": "#95BF47",
    "DigitalOcean": "#0080FF", "Notion": "#E5E7EB", "Linear": "#5E6AD2", "Doppler": "#7C6CF6",
    "Clave privada": "#EF4444",
    # secretos genéricos
    "Contraseña": "#F87171", "Secreto": "#FB923C", "Token": "#FBBF24", "API key": "#F59E0B",
    "JWT": "#E879F9", "Webhook": "#F472B6", "Hex": "#FCA5A5",
    # configuración
    "Base de datos": "#FB923C", "URL": "#60A5FA", "Ruta": "#C084FC", "Puerto": "#F472B6",
    "ID": "#38BDF8", "Número": "#FCD34D", "Booleano": "#34D399", "Email": "#F9A8D4",
    "UUID": "#A78BFA", "IP": "#2DD4BF", "Host": "#2DD4BF", "Certificado": "#FDE68A",
    "Clave pública": "#FDE68A", "PEM": "#FDE68A", "Referencia": "#22D3EE", "Texto": "#94A3B8",
}
CATEGORY_COLORS = {SERVICE: "#22D3EE", SECRET: AMBER, CONFIG: "#94A3B8"}
EMPTY_COLOR = "#EF4444"
TABLE_BG = "#0A0F14"


def _blend(color: str, base: str = TABLE_BG, amount: float = 0.22) -> str:
    """``color`` mezclado con el fondo: para el relleno suave de las etiquetas."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b))


def pill(text: str, color: str) -> Text:
    return Text(f" {text} ", style=f"bold {color} on {_blend(color)}")

Copier = Callable[[str], None]


def truncate(text: str, width: int = VALUE_WIDTH) -> str:
    text = text.replace("\n", "⏎")
    return text if len(text) <= width else text[: width - 1] + "…"


def default_copier(value: str) -> None:
    clipboard.copy_temporarily(value, 30)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self, message: str, confirm_label: str = "Borrar"):
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog danger") as dialog:
            dialog.border_title = "Confirmar"
            yield Static(self.message)
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.confirm_label, id="confirm", variant="error")
                yield Button("Cancelar", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class EditScreen(ModalScreen["tuple[str, str, str] | None"]):
    """Crea o edita un secreto: devuelve (clave, valor, nota)."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar"), Binding("ctrl+s", "save", "Guardar")]

    def __init__(self, title: str, key: str = "", value: str = "", note: str = ""):
        super().__init__()
        self.title_text = title
        self.initial = (key, value, note)

    def compose(self) -> ComposeResult:
        key, value, note = self.initial
        with Vertical(classes="dialog") as dialog:
            dialog.border_title = self.title_text
            dialog.border_subtitle = "ctrl+s guardar · esc cancelar"
            yield Label("Clave")
            yield Input(value=key, placeholder="DISCORD_TOKEN", id="key")
            yield Label("Valor")
            yield Input(value=value, password=True, id="value")
            yield Checkbox("Mostrar valor", id="show")
            yield Label("Nota (opcional)")
            yield Input(value=note, placeholder="Para qué es", id="note")
            yield Static("", id="error", classes="error-text")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Guardar", id="save", variant="success")
                yield Button("Cancelar", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value" if self.initial[0] else "#key", Input).focus()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self.query_one("#value", Input).password = not event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_save(self) -> None:
        key = self.query_one("#key", Input).value.strip()
        value = self.query_one("#value", Input).value
        note = self.query_one("#note", Input).value.strip()
        if not KEY_RE.match(key):
            self.query_one("#error", Static).update("La clave solo admite letras, números y _ (sin empezar por número).")
            return
        self.dismiss((key, value, note))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ScanScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Cerrar")]

    def __init__(self, title: str, findings: list[Finding], files: int):
        super().__init__()
        self.title_text = title
        self.findings = findings
        self.files = files

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide" if self.findings else "dialog") as dialog:
            dialog.border_title = f"Scan · {self.title_text}"
            if self.findings:
                yield Static(f"[b $warning]⚠ {len(self.findings)} hallazgos[/] "
                             f"[dim]en {self.files} ficheros[/]")
                table = DataTable(id="findings", cursor_type="row", zebra_stripes=True)
                table.add_columns("Qué", "Dónde", "Valor", "En la bóveda como")
                for f in self.findings:
                    table.add_row(f.label, f.where, f.masked, ", ".join(f.vault))
                yield table
            else:
                yield Static(f"[b $success]✓ Nada sospechoso[/] [dim]en {self.files} ficheros[/]")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cerrar", id="close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class EnvVaultApp(App[str]):
    TITLE = "EnvVault"
    CSS = CSS

    BINDINGS = [
        Binding("slash", "focus_search", "Buscar"),
        Binding("r", "reveal", "Revelar"),
        Binding("c", "copy", "Copiar"),
        Binding("n", "new", "Nuevo"),
        Binding("e", "edit", "Editar"),
        Binding("x,delete", "delete", "Borrar"),
        Binding("s", "scan", "Scan"),
        Binding("l", "lock", "Bloquear"),
        Binding("escape", "clear_search", "Limpiar", show=False),
        Binding("q", "quit", "Salir"),
    ]

    def __init__(self, vault: Vault, lock_at: float | None = None,
                 on_lock: Callable[[], object] | None = None, copier: Copier | None = None):
        super().__init__()
        self.register_theme(THEME)
        self.theme = THEME.name
        self.vault = vault
        self.lock_at = lock_at
        self.on_lock = on_lock
        self.copier = copier or default_copier
        self.scope: tuple[str | None, str | None] = (None, None)
        self.revealed: set[Location] = set()
        self.search_text = ""
        self.flagged: set[str] = set()
        self.shown_keys: list[str] = []

    @property
    def data(self):
        return self.vault.data

    # ----------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("", id="brand")
            yield Static("", id="lock")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("BÓVEDA", classes="section-title")
                yield Tree("Bóveda", id="scopes")
            with Vertical(id="right"):
                yield Input(placeholder="⌕  Buscar por clave o nota   /", id="search")
                with Vertical(id="table-card", classes="card"):
                    yield DataTable(id="secrets", cursor_type="row", zebra_stripes=True, cell_padding=1)
                with Vertical(id="detail-card", classes="card"):
                    yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one("#scopes", Tree)
        tree.show_root = False
        tree.guide_depth = 3
        self.query_one("#detail-card").border_title = "Detalle"
        self.build_tree()
        self.refresh_table()
        self.call_after_refresh(self.refresh_table)  # ya con el ancho real de la tabla
        self.query_one("#secrets", DataTable).focus()
        self.tick()
        if self.lock_at is not None:
            self.set_interval(1, self.tick)

    def build_tree(self) -> None:
        tree = self.query_one("#scopes", Tree)
        tree.clear()
        shared = tree.root.add_leaf(self._tree_label("◎", SHARED, len(self.data.shared)), data=(None, None))
        target = shared
        for project in sorted(self.data.projects.values(), key=lambda p: p.name.lower()):
            label = Text.assemble(("◆ ", AMBER), (project.name, "bold"))
            if project.name in self.flagged:
                label.append(" ⚠", style=f"bold {AMBER}")
            node = tree.root.add(label, data=(project.name, None), expand=True)
            for env in project.envs:
                leaf = node.add_leaf(self._tree_label("·", env, len(project.envs[env])),
                                     data=(project.name, env))
                if (project.name, env) == self.scope:
                    target = leaf
        tree.root.expand()
        self.update_header()
        # Hasta el siguiente refresco el árbol no sabe en qué línea queda cada nodo.
        self.call_after_refresh(tree.move_cursor, target)

    @staticmethod
    def _tree_label(icon: str, name: str, count: int) -> Text:
        return Text.assemble((f"{icon} ", MUTED), name, (f"  {count}", MUTED))

    def update_header(self) -> None:
        projects = len(self.data.projects)
        total = len(self.data.shared) + sum(len(s) for p in self.data.projects.values()
                                            for s in p.envs.values())
        brand = Text()
        brand.append(" 🔐 EnvVault ", style=f"bold #0A0F14 on {EMERALD}")
        brand.append("   ")
        brand.append(f"{projects} {'proyecto' if projects == 1 else 'proyectos'}", style="bold")
        brand.append("  ·  ", style=MUTED)
        brand.append(f"{total} {'secreto' if total == 1 else 'secretos'}", style="bold")
        brand.append("  ·  cifrado en local", style=MUTED)
        self.query_one("#brand", Static).update(brand)

    # ------------------------------------------------------------------ tabla
    def current_secrets(self):
        project, env = self.scope
        try:
            return self.data.scope(project, env)
        except EnvVaultError:
            self.scope = (None, None)
            return self.data.shared

    def refresh_table(self) -> None:
        project, env = self.scope
        table = self.query_one("#secrets", DataTable)
        cursor = table.cursor_row
        # Con columns=True los anchos se recalculan; si no, solo crecen y acaban desbordando.
        table.clear(columns=True)
        table.add_columns(*COLUMNS)
        secrets = self.current_secrets()
        query = self.search_text.lower()
        self.shown_keys = [k for k, s in sorted(secrets.items())
                           if not query or query in k.lower() or query in s.note.lower()]
        rows = []
        for key in self.shown_keys:
            secret = secrets[key]
            loc = Location(project, env, key)
            if loc in self.revealed:
                try:
                    value = (self.data.resolve_value(loc), f"bold {MINT}")
                except EnvVaultError as exc:
                    value = (str(exc), "red")
            elif secret.is_reference:
                value = (secret.value, THEME.accent)
            elif not secret.value.strip():
                value = ("(vacío)", f"italic {MUTED}")
            else:
                value = (mask(secret.value), MUTED)
            rows.append((key, value, self.kind_cell(loc, secret), secret.note))
        value_width, note_width = self.column_widths(rows, table)
        for key, (value, style), kind, note in rows:
            table.add_row(Text(key, style="bold"), Text(truncate(value, value_width), style=style), kind,
                          Text(truncate(note, note_width), style=MUTED), key=key)
        if self.shown_keys:
            table.move_cursor(row=min(max(cursor, 0), len(self.shown_keys) - 1))
        self.set_table_title(f"◎ {SHARED}" if project is None else f"{project} · {env}",
                             f"{len(self.shown_keys)} de {len(secrets)}" if query else str(len(secrets)))
        self.update_detail()

    @staticmethod
    def column_widths(rows: list, table: DataTable) -> tuple[int, int]:
        """Anchos de Valor y Nota para que la tabla quepa sin scroll horizontal.

        Clave y Tipo se muestran enteros; Valor y Nota se recortan (el detalle los
        enseña completos). Mientras la tabla no tiene tamaño se usa uno razonable.
        """
        available = (table.size.width or 80) - 1  # 1 columna para la barra de scroll
        key_width = max([len(COLUMNS[0])] + [len(r[0]) for r in rows])
        kind_width = max([len(COLUMNS[2])] + [r[2].cell_len for r in rows])
        rest = available - key_width - kind_width - 2 * len(COLUMNS)  # cell_padding=1 por lado
        notes = max([0] + [len(r[3]) for r in rows])
        note_width = min(notes, max(len(COLUMNS[3]), rest // 3)) if notes else len(COLUMNS[3])
        value_width = min(VALUE_WIDTH, max(8, rest - note_width))
        return value_width, note_width

    def on_resize(self) -> None:
        self.call_after_refresh(self.refresh_table)

    def kind_of(self, loc: Location, secret) -> tuple[str, str] | None:
        """(nombre, color) del tipo del secreto; None si está vacío."""
        value, prefix = secret.value, ""
        if secret.is_reference:  # el tipo es el del valor al que apunta
            try:
                value, prefix = self.data.resolve_value(loc), "↪ "
            except EnvVaultError:
                pass
        described = describe(value, loc.key)
        if described is None:
            return None
        name, category = described
        return prefix + name, KIND_COLORS.get(name, CATEGORY_COLORS[category])

    def kind_cell(self, loc: Location, secret) -> Text:
        kind = self.kind_of(loc, secret)
        return pill(*kind) if kind else pill("Vacío", EMPTY_COLOR)

    def set_table_title(self, title: str, count: str) -> None:
        card = self.query_one("#table-card")
        card.border_title = f" {title} "
        card.border_subtitle = f" {count} {'secreto' if count == '1' else 'secretos'} "

    def selected_key(self) -> str | None:
        table = self.query_one("#secrets", DataTable)
        if not self.shown_keys or table.cursor_row < 0:
            return None
        return self.shown_keys[min(table.cursor_row, len(self.shown_keys) - 1)]

    def selected_location(self) -> Location | None:
        key = self.selected_key()
        return Location(self.scope[0], self.scope[1], key) if key else None

    def update_detail(self) -> None:
        detail = self.query_one("#detail", Static)
        loc = self.selected_location()
        project = self.data.find_project(self.scope[0]) if self.scope[0] else None
        card = self.query_one("#detail-card")
        card.border_title = " Detalle "
        card.border_subtitle = ""

        def row(label: str, value: str) -> str:
            return f"[{MUTED}]{label:<11}[/]{value}"

        lines = []
        if loc is not None:
            secret = self.data.lookup(loc)
            if secret is not None:
                card.border_title = f" {loc} "
                if loc in self.revealed:
                    try:
                        value = f"[b {MINT}]{escape(self.data.resolve_value(loc))}[/]"
                    except EnvVaultError as exc:
                        value = f"[red]{escape(str(exc))}[/]"
                    card.border_subtitle = " r ocultar · c copiar "
                elif secret.is_reference:
                    value = f"[{THEME.accent}]↪ {escape(secret.value)}[/]"
                    card.border_subtitle = " r resolver · c copiar "
                elif not secret.value.strip():
                    value = f"[{EMPTY_COLOR}]vacío[/] [{MUTED}]· pulsa [b {EMERALD}]e[/] para rellenarlo[/]"
                    card.border_subtitle = " e editar "
                else:
                    value = f"[{MUTED}]{escape(mask(secret.value))}[/]"
                    card.border_subtitle = " r revelar · c copiar "
                lines.append(row("Valor", value))
                kind = self.kind_of(loc, secret)
                if kind is not None:
                    name, color = kind
                    service = detect_kind(secret.value)  # su nombre largo, p. ej. «Token de bot de Discord»
                    lines.append(row("Tipo", f"[b {color}]{escape(service.label if service else name)}[/]"))
                if secret.note:
                    lines.append(row("Nota", escape(secret.note)))
                dates = f"creado {secret.created_at[:10]} · actualizado {secret.updated_at[:10]}"
                if secret.expires:
                    dates += f" · [b {AMBER}]caduca {secret.expires}[/]"
                lines.append(row("Fechas", dates))
                users = self.data.referrers(loc)
                if users:
                    lines.append(row("Lo usan", ", ".join(escape(str(u)) for u in users)))
        elif not self.current_secrets():
            lines.append(f"[{MUTED}]Aún no hay secretos aquí. Pulsa [b {EMERALD}]n[/] para añadir uno.[/]")
        if project and project.paths:
            lines.append(row("Carpetas", ", ".join(escape(p) for p in project.paths)))
        detail.update("\n".join(lines))

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data
        if data is None:
            return
        project, env = data
        if project is not None and env is None:
            envs = list(self.data.project(project).envs)
            env = envs[0] if envs else None
            if env is None:
                self.scope = (project, None)
                self.query_one("#secrets", DataTable).clear()
                self.shown_keys = []
                self.set_table_title(project, "0")
                self.update_detail()
                return
        if (project, env) != self.scope:
            self.scope = (project, env)
            self.refresh_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.update_detail()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search_text = event.value.strip()
            self.refresh_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#secrets", DataTable).focus()

    # ----------------------------------------------------------------- tiempo
    def tick(self) -> None:
        label = self.query_one("#lock", Static)
        if self.lock_at is None:
            label.update(f"[{MINT}]🔓 abierta[/]")
            return
        remaining = self.lock_at - time.time()
        if remaining <= 0:
            self.lock("timeout")
            return
        minutes, seconds = divmod(int(remaining), 60)
        style = f"b {AMBER}" if remaining < 60 else MINT
        label.update(f"[{MUTED}]🔓 se bloquea en[/] [{style}]{minutes}:{seconds:02d}[/]")

    def lock(self, reason: str = "locked") -> None:
        if self.on_lock:
            self.on_lock()
        self.exit(reason)

    # ---------------------------------------------------------------- acciones
    def _typing(self) -> bool:
        return isinstance(self.focused, Input)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Mientras se escribe en el buscador, las letras no disparan acciones.
        if action in {"reveal", "copy", "new", "edit", "delete", "scan", "lock", "quit"} and self._typing():
            return False
        return True

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        search = self.query_one("#search", Input)
        search.value = ""
        self.query_one("#secrets", DataTable).focus()

    def action_reveal(self) -> None:
        loc = self.selected_location()
        if loc is None:
            return
        self.revealed ^= {loc}
        self.refresh_table()

    def action_copy(self) -> None:
        loc = self.selected_location()
        if loc is None:
            return
        try:
            self.copier(self.data.resolve_value(loc))
        except EnvVaultError as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(f"{loc.key} copiado. Se borra del portapapeles en 30 s.")

    def _save(self) -> bool:
        try:
            self.vault.save()
        except (EnvVaultError, OSError) as exc:
            self.notify(f"No se ha podido guardar: {exc}", severity="error", timeout=8)
            return False
        return True

    def action_new(self) -> None:
        project, env = self.scope
        if project is not None and env is None:
            env = "dev"
        title = f"Nuevo secreto en {SHARED if project is None else f'{project} · {env}'}"

        def done(result: tuple[str, str, str] | None) -> None:
            if result is None:
                return
            key, value, note = result
            loc = Location(project, env, key)
            if self.data.lookup(loc) is not None:
                self.notify(f"{key} ya existe; edítalo con e.", severity="warning")
                return
            self.data.set(loc, value, note=note)
            if self._save():
                self.scope = (project, env)
                self.build_tree()
                self.refresh_table()
                if key in self.shown_keys:
                    self.query_one("#secrets", DataTable).move_cursor(row=self.shown_keys.index(key))
                self.notify(f"✓ {loc} guardado")

        self.push_screen(EditScreen(title), done)

    def action_edit(self) -> None:
        loc = self.selected_location()
        if loc is None:
            return
        secret = self.data.get(loc)

        def done(result: tuple[str, str, str] | None) -> None:
            if result is None:
                return
            key, value, note = result
            if key != loc.key:
                users = self.data.referrers(loc)
                if users:
                    self.notify("No se puede renombrar: lo usan " + ", ".join(map(str, users)), severity="error")
                    return
                if self.data.lookup(Location(loc.project, loc.env, key)) is not None:
                    self.notify(f"Ya existe {key}.", severity="error")
                    return
                old = self.data.remove(loc)
                new = self.data.set(Location(loc.project, loc.env, key), value, note=note, expires=old.expires or "")
                new.created_at = old.created_at
            else:
                self.data.set(loc, value, note=note)
            if self._save():
                self.refresh_table()
                self.notify(f"✓ {Location(loc.project, loc.env, key)} guardado")

        self.push_screen(EditScreen(f"Editar {loc}", loc.key, secret.value, secret.note), done)

    def action_delete(self) -> None:
        loc = self.selected_location()
        if loc is None:
            return
        users = self.data.referrers(loc)
        if users:
            self.notify("No se puede borrar: lo usan " + ", ".join(map(str, users)), severity="error", timeout=6)
            return

        def done(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self.data.remove(loc)
            self.revealed.discard(loc)
            if self._save():
                self.build_tree()
                self.refresh_table()
                self.notify(f"{loc} borrado")

        self.push_screen(ConfirmScreen(f"¿Borrar [b]{escape(str(loc))}[/]? No se puede deshacer."), done)

    def action_scan(self) -> None:
        project = self.data.find_project(self.scope[0]) if self.scope[0] else None
        if project is None:
            self.notify("Elige un proyecto para revisar sus carpetas.", severity="warning")
            return
        folders = [Path(p) for p in project.paths if Path(p).is_dir()]
        if not folders:
            self.notify(f"{project.name} no tiene carpetas enlazadas (envvault link).", severity="warning")
            return
        self.notify(f"Revisando {project.name}…")
        self.run_scan(project.name, folders)

    @work(thread=True, exclusive=True, group="scan")
    def run_scan(self, name: str, folders: list[Path]) -> None:
        scanner = Scanner(self.vault.secret_values())
        findings: list[Finding] = []
        files = 0
        try:
            for folder in folders:
                result = scanner.scan_tree(folder)
                files += result.files
                findings.extend(result.findings)
        except EnvVaultError as exc:
            self.call_from_thread(self.notify, str(exc), severity="error")
            return
        self.call_from_thread(self.show_scan, name, findings, files)

    def show_scan(self, name: str, findings: list[Finding], files: int) -> None:
        if findings:
            self.flagged.add(name)
        else:
            self.flagged.discard(name)
        self.build_tree()
        self.push_screen(ScanScreen(name, findings, files))

    def action_lock(self) -> None:
        self.lock("locked")
