"""Portapapeles con borrado automático.

``copy_temporarily`` copia el valor y lanza un proceso aparte que, pasados unos
segundos, vacía el portapapeles si sigue conteniendo ese mismo valor. En Windows
además se marca la copia para que no entre en el historial (Win+V) ni se sincronice.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time

from envvault.errors import EnvVaultError


class ClipboardError(EnvVaultError):
    pass


# ------------------------------------------------------------------- Windows
def _win_api():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return ctypes, user32, kernel32


def _win_open(user32) -> None:
    for _ in range(20):  # otro programa puede tenerlo abierto un instante
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise ClipboardError("No se puede abrir el portapapeles de Windows.")


def _win_alloc(ctypes, kernel32, data: bytes):
    handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    if not handle:
        raise ClipboardError("Sin memoria para el portapapeles.")
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    return handle


def _win_set(text: str) -> None:
    ctypes, user32, kernel32 = _win_api()
    _win_open(user32)
    try:
        user32.EmptyClipboard()
        if not text:
            return
        handle = _win_alloc(ctypes, kernel32, text.encode("utf-16-le") + b"\x00\x00")
        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT
            kernel32.GlobalFree(handle)
            raise ClipboardError("Windows no ha aceptado el texto en el portapapeles.")
        for name, value in (("ExcludeClipboardContentFromMonitorProcessing", b"\x00"),
                            ("CanIncludeInClipboardHistory", b"\x00\x00\x00\x00"),
                            ("CanUploadToCloudClipboard", b"\x00\x00\x00\x00")):
            fmt = user32.RegisterClipboardFormatW(name)
            if fmt:
                extra = _win_alloc(ctypes, kernel32, value)
                if not user32.SetClipboardData(fmt, extra):
                    kernel32.GlobalFree(extra)
    finally:
        user32.CloseClipboard()


def _win_get() -> str:
    ctypes, user32, kernel32 = _win_api()
    _win_open(user32)
    try:
        handle = user32.GetClipboardData(13)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer) if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------- macOS / Linux
def _commands() -> tuple[list[str], list[str], list[str] | None]:
    """Devuelve (copiar, leer, vaciar); ``vaciar`` es None si basta con copiar ""."""
    if sys.platform == "darwin":
        return ["pbcopy"], ["pbpaste"], None
    # La herramienta se elige según la sesión gráfica, no solo según lo instalado:
    # wl-copy falla en X11 y ninguna funciona por SSH sin pantalla.
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return ["wl-copy"], ["wl-paste", "--no-newline"], ["wl-copy", "--clear"]
    if os.environ.get("DISPLAY"):  # X11, o XWayland dentro de Wayland
        if shutil.which("xclip"):
            return (["xclip", "-selection", "clipboard"],
                    ["xclip", "-selection", "clipboard", "-o"], None)
        if shutil.which("xsel"):
            return (["xsel", "--clipboard", "--input"], ["xsel", "--clipboard", "--output"],
                    ["xsel", "--clipboard", "--clear"])
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        raise ClipboardError("No hay sesión gráfica (¿SSH?): no se puede usar el portapapeles.")
    raise ClipboardError("No hay herramienta de portapapeles (instala wl-clipboard o xclip).")


def set_text(text: str) -> None:
    if sys.platform == "win32":
        _win_set(text)
        return
    copy_cmd, _, clear_cmd = _commands()
    cmd = clear_cmd if not text and clear_cmd else copy_cmd
    # xclip y wl-copy dejan un proceso en segundo plano sirviendo el portapapeles que
    # hereda stdout/stderr: con tuberías, run() esperaría a que se cerrasen y se
    # colgaría. stdout va a DEVNULL y stderr a un fichero temporal, que no bloquea.
    with tempfile.TemporaryFile() as err:
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=err)
        except subprocess.CalledProcessError as exc:
            err.seek(0)
            detail = err.read().decode("utf-8", "replace").strip() or f"código {exc.returncode}"
            raise ClipboardError(f"No se ha podido copiar: {detail}") from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ClipboardError(f"No se ha podido copiar: {exc}") from exc


def get_text() -> str:
    if sys.platform == "win32":
        return _win_get()
    _, paste_cmd, _ = _commands()
    try:
        return subprocess.run(paste_cmd, check=True, capture_output=True,
                              timeout=10).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ClipboardError(f"No se ha podido leer el portapapeles: {exc}") from exc


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def copy_temporarily(text: str, seconds: int = 30) -> None:
    set_text(text)
    if seconds <= 0:
        return
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    # Solo el hash viaja en la línea de comandos: el valor no aparece en la lista de procesos.
    subprocess.Popen(
        [sys.executable, "-m", "envvault.clipboard", str(seconds), _digest(text)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags, start_new_session=sys.platform != "win32", close_fds=True,
    )


def _clear_later(seconds: float, digest: str) -> None:
    time.sleep(seconds)
    try:
        if _digest(get_text()) == digest:
            set_text("")
    except ClipboardError:
        pass


if __name__ == "__main__":  # proceso de borrado lanzado por copy_temporarily
    _clear_later(float(sys.argv[1]), sys.argv[2])
