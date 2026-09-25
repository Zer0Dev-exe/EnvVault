# EnvVault

Bóveda cifrada para los `.env` y tokens de **todos tus proyectos**. Guarda cada secreto una
vez, pásaselo a cada bot sin copiar y pegar, y entérate si algún token se ha colado en un repo.

![EnvVault: la TUI con los proyectos a la izquierda y los secretos de HPBot · prod](docs/screenshot.png)

- **Cifrada de verdad**: Argon2id + AES-256-GCM, con clave de recuperación. Sin la contraseña,
  el fichero no dice ni cómo se llaman tus proyectos.
- **Sin `.env` sueltos**: `envvault run -- node index.js` arranca el bot con sus variables en
  memoria. No queda ningún fichero que se pueda subir a GitHub por error.
- **Secretos compartidos**: la URI de Mongo o la API key de OpenAI se guardan una vez y cada
  proyecto las referencia con `${compartidos.MONGO_URI}`.
- **Escáner de filtraciones**: busca tokens de Discord, GitHub, OpenAI, Anthropic, Google,
  Telegram, AWS… en tus carpetas y en **todo el historial de git**.
- **Comprobación de tokens**: pregunta a Discord, GitHub, etc. si cada token sigue siendo válido.

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -e .
```

Instala dos comandos equivalentes: `envvault` y `ev`. Para tenerlos en cualquier terminal sin
activar el venv: `pipx install -e .`

## En dos minutos

```bash
envvault init                      # crea la bóveda y te da la clave de recuperación
envvault import ~/proyectos        # busca todos los .env y los importa por proyecto
cd ~/proyectos/HPBot
envvault link                      # enlaza esta carpeta con el proyecto "HPBot"
envvault run -- node index.js      # arranca el bot con sus variables
```

Después de importar puedes borrar los `.env`: `run` ya no los necesita.

## Comandos

| Comando | Qué hace |
|---|---|
| `init` | Crea la bóveda (`~/.envvault/vault.enc`) con tu contraseña maestra |
| `unlock [-m 60]` / `lock` | Abre la bóveda un rato (15 min por defecto) o la cierra ya |
| `status` | Dónde está la bóveda, si está abierta y qué proyecto hay enlazado aquí |
| `import <carpeta>` | Busca `.env`, `.env.local`, `.env.production`… (y `config.json` con tokens) y los importa. `--dry-run` para ver antes, `--link` para enlazar cada carpeta, `--overwrite` para pisar valores |
| `link [proyecto] [-e prod]` | Crea `.envvault.toml` en la carpeta (no tiene secretos: se puede subir a git) |
| `unlink` | Quita el enlace |
| `run -- <comando>` | Ejecuta el comando con las variables inyectadas (`--keep-existing` para no pisar las que ya existan) |
| `set CLAVE [valor]` | Guarda un secreto. Sin valor te lo pide oculto (así no queda en el historial de la shell). `--note`, `--expires 2026-12-31` |
| `get CLAVE` | Lo copia al portapapeles y lo borra a los 30 s. `--show` lo muestra, `--raw` para scripts |
| `rm CLAVE` | Lo borra (se niega si otro secreto lo referencia, salvo con `--force`) |
| `ls [proyecto]` | Lista proyectos, o los secretos de uno (enmascarados). `--shared` para los compartidos |
| `rotate CLAVE` | Pide el valor nuevo y lo cambia en **todos** los proyectos que tenían el mismo token |
| `drop <proyecto> [-e env]` | Borra un proyecto entero o uno de sus entornos |
| `pull` | Escribe el `.env` en disco si de verdad lo necesitas, y lo añade al `.gitignore` |
| `example` | Genera `.env.example` con las claves (y las notas como comentarios), sin valores |
| `scan [carpeta] [-H] [--all]` | Busca tokens filtrados; `-H` revisa también el historial de git y `--all` las carpetas de todos tus proyectos |
| `check [proyecto]` | Comprueba si los tokens siguen siendo válidos |
| `passwd` | Cambia la contraseña maestra |
| `recover` | Pone una contraseña nueva usando la clave de recuperación |
| `recovery-key` | Genera otra clave de recuperación (la anterior deja de valer) |
| `tui` | Interfaz interactiva (también al ejecutar `envvault` sin argumentos) |

`set`, `get`, `rm` y `rotate` usan el proyecto enlazado en la carpeta actual; si no, indícalo
con `-p HPBot -e prod`, o `--shared` para los compartidos.

## Cómo se organiza

```
Bóveda
├── compartidos            ← secretos que usan varios proyectos
│   ├── MONGO_URI
│   └── OPENAI_API_KEY
└── proyectos
    ├── HPBot
    │   ├── dev   DISCORD_TOKEN, CLIENT_ID, MONGO_URI = ${compartidos.MONGO_URI}
    │   └── prod  DISCORD_TOKEN, ...
    └── BordaAPI
        └── dev   POCKETBASE_URL, ...
```

**Referencias** dentro de un valor:

| Sintaxis | Apunta a |
|---|---|
| `${compartidos.CLAVE}` | Un secreto compartido (también vale `${shared.CLAVE}`) |
| `${Proyecto.entorno.CLAVE}` | Un secreto de otro proyecto |
| `${CLAVE}` | Otro secreto del mismo entorno (si no existe, se deja tal cual) |
| `$${...}` | El texto `${...}` literal |

Se pueden mezclar con texto: `mongodb://admin:${compartidos.DB_PASS}@host/db`.

Al importar, `.env` y `.env.development` van al entorno `dev`, y `.env.production` a `prod`.
`.env.local` pisa a `.env`, como en Next.js o Vite. Las plantillas (`.env.example`,
`.env.sample`…) se ignoran.

## TUI

| Tecla | Acción |
|---|---|
| `/` | Buscar por clave o nota (Esc para limpiar) |
| `r` | Revelar / ocultar el valor (el completo sale en el panel de abajo) |
| `c` | Copiar al portapapeles (se borra a los 30 s) |
| `n` / `e` | Nuevo secreto / editar el seleccionado |
| `x` / `Supr` | Borrar (con confirmación) |
| `s` | Escanear las carpetas del proyecto (los proyectos con hallazgos se marcan con ⚠) |
| `l` | Bloquear y salir |
| `q` | Salir |

Arriba a la derecha se ve cuánto falta para que la bóveda se bloquee sola.

## Seguridad

- **Cifrado por sobres.** Una clave aleatoria de 256 bits cifra el contenido con AES-256-GCM.
  Esa clave se guarda cifrada dos veces: con tu contraseña (pasada por Argon2id: 64 MiB,
  3 iteraciones) y con la clave de recuperación. Cambiar la contraseña no recifra los datos.
- **Nada en claro.** El fichero solo tiene en claro los parámetros de cifrado. Los nombres de
  proyectos y variables también van cifrados. Cada bloque va ligado al id de la bóveda: no se
  puede mover una ranura o el contenido de una bóveda a otra.
- **Escritura segura.** Primero se escribe un fichero temporal y luego se renombra, dejando la
  versión anterior en `vault.enc.bak`. Si se va la luz a mitad, no pierdes nada.
- **Sesión.** Al desbloquear, la clave se guarda en el llavero del sistema (Administrador de
  credenciales en Windows, Llavero en macOS, Secret Service en Linux) con caducidad. Cualquier
  programa que ejecutes con tu usuario podría leerla mientras dure; usa `envvault lock` al
  terminar si te preocupa.
- **Portapapeles.** En Windows la copia se marca para que no entre en el historial (Win+V) ni
  se sincronice en la nube, y se borra a los 30 s si sigue ahí.
- **Sin puertas traseras.** Si pierdes la contraseña **y** la clave de recuperación, la bóveda
  es irrecuperable.
- **Tokens a su dueño.** `check` solo envía cada token al servicio que lo emitió, por HTTPS.

## El escáner

`envvault scan` reconoce tokens de bot de Discord y sus webhooks, tokens de GitHub, API keys de
OpenAI, Anthropic y Google, tokens de bot de Telegram, claves de AWS, Slack y Stripe, URIs de
bases de datos con contraseña, claves privadas y asignaciones del tipo `password = "..."`. Con
la bóveda abierta reconoce también cualquier valor que tengas guardado, aunque no siga ningún
formato conocido, y te dice con qué nombre está en la bóveda.

- En los repos git solo mira lo que git **no** ignora (lo que acabaría subido). También avisa de
  los `.env` que están commiteados o que no están en el `.gitignore`.
- Con `-H` recorre el historial de todas las ramas. Un token que se subió y luego se borró sigue
  ahí: rótalo con `envvault rotate`.
- Si encuentra algo, sale con código 1, así que sirve en un hook de pre-commit o en CI.

## Variables de entorno

| Variable | Para qué |
|---|---|
| `ENVVAULT_HOME` | Carpeta de la bóveda (por defecto `~/.envvault`) |
| `ENVVAULT_TIMEOUT` | Minutos que dura la sesión (por defecto 15) |
| `ENVVAULT_PASSWORD` | Contraseña para usos desatendidos (no crea sesión). Úsala con cuidado |

Para bots que se reinician solos (pm2, un servicio…), la sesión puede haber caducado cuando
arrancan. Tienes dos opciones: `envvault pull` para dejarles su `.env` (protegido en el
`.gitignore`), o arrancarlos con `ENVVAULT_PASSWORD` definido solo en ese servicio.

## Llevarla a otro PC

`vault.enc` va cifrado, así que puedes copiarlo a otro PC, a OneDrive o a un repo privado, y
abrirlo allí con tu contraseña. Todavía no hay una sincronización automática que combine los
cambios hechos en dos sitios a la vez.

## Desarrollo

```bash
pip install -e ".[dev]"
pytest
```

Los tests no tocan tu bóveda, tu llavero ni tu portapapeles: usan una carpeta temporal, una
sesión en memoria y un Argon2 rápido. Las APIs de `check` se simulan con `respx`, y los tokens
de prueba se montan por partes para que el código no contenga nada que parezca un secreto real.
