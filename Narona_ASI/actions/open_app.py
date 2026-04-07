"""
actions/open_app.py – Abre aplicaciones en Windows/Linux/macOS.
Patrón: misma firma (parameters, response, player) que todas las actions.
"""

import subprocess
import sys


# Mapa de nombres comunes → comandos en cada plataforma
_APP_MAP_WINDOWS = {
    "whatsapp":   "start whatsapp:",
    "chrome":     "start chrome",
    "firefox":    "start firefox",
    "spotify":    "start spotify:",
    "notepad":    "notepad",
    "calculadora":"calc",
    "calculator": "calc",
    "paint":      "mspaint",
    "minecraft":  "start minecraft:",
    "youtube":    "start https://www.youtube.com",
    "netflix":    "start https://www.netflix.com",
    "vlc":        "start vlc",
    "word":       "start winword",
    "excel":      "start excel",
    "powerpoint": "start powerpnt",
    "explorer":   "explorer",
    "task manager": "taskmgr",
    "administrador de tareas": "taskmgr",
    "bloc de notas": "notepad",
}

_APP_MAP_LINUX = {
    "chrome":   "google-chrome",
    "firefox":  "firefox",
    "spotify":  "spotify",
    "vlc":      "vlc",
    "calculator": "gnome-calculator",
    "calculadora": "gnome-calculator",
}

_APP_MAP_MACOS = {
    "chrome":   "open -a 'Google Chrome'",
    "firefox":  "open -a Firefox",
    "spotify":  "open -a Spotify",
    "vlc":      "open -a VLC",
    "calculator": "open -a Calculator",
    "calculadora": "open -a Calculator",
}


def _get_platform() -> str:
    if sys.platform == "win32":  return "windows"
    if sys.platform == "darwin": return "macos"
    return "linux"


def open_app(
    parameters: dict,
    response=None,
    player=None,
) -> str:
    """
    Abre una aplicación en el sistema operativo.

    Parámetros:
        app_name : str  Nombre de la app (required).
        platform : str  "windows" | "linux" | "macos" (default: auto-detectado).

    Returns:
        str: Mensaje de resultado.
    """
    params   = parameters or {}
    app_name = params.get("app_name", "").strip()
    platform = params.get("platform", _get_platform()).lower().strip()

    if not app_name:
        return "No se especificó ninguna aplicación."

    app_lower = app_name.lower()
    print(f"[OpenApp] 🚀 Abriendo: {app_name!r}  (plataforma: {platform})")

    # Buscar en el mapa de apps conocidas
    if platform == "windows":
        cmd = _APP_MAP_WINDOWS.get(app_lower)
        if cmd is None:
            # Intentar directamente como nombre de ejecutable
            cmd = f"start {app_name}"
    elif platform == "macos":
        cmd = _APP_MAP_MACOS.get(app_lower)
        if cmd is None:
            cmd = f"open -a '{app_name}'"
    else:  # linux
        cmd = _APP_MAP_LINUX.get(app_lower)
        if cmd is None:
            # Usar el nombre tal cual (conocido o fallback)
            cmd = app_lower

    try:
        subprocess.Popen(cmd, shell=True)

        print(f"[OpenApp] ✅ Lanzado: {cmd}")
        return f"¡Abrí {app_name} ahora mismo! 🚀"

    except Exception as exc:
        print(f"[OpenApp] ❌ Error: {exc}")
        return f"No pude abrir {app_name}: {exc}"
