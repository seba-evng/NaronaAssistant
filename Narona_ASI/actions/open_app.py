"""
actions/open_app.py – Lanzador del juego Godot creado por el equipo.

Solo existe una acción posible: abrir el juego ubicado en el Desktop
de la Raspberry Pi 5 con el comando ./JuegoFinalV2.arm64 --fullscreen.

Gemini llama a esta herramienta cuando el niño dice frases como:
  "Quiero jugar", "Juguemos", "Tengo ganas de jugar", etc.
"""

import os
import subprocess


# Ruta al ejecutable del juego en la Raspberry Pi 5
_GAME_DIR  = os.path.expanduser("~/Desktop")
_GAME_BIN  = "./JuegoFinalV2.arm64"
_GAME_ARGS = ["--fullscreen"]


def open_app(
    parameters: dict,
    response=None,
    player=None,
) -> str:
    """
    Lanza el juego Godot del equipo en la Raspberry Pi 5.

    Devuelve un mensaje que Gemini usa para confirmar al niño que
    el juego está abriendo.
    """
    print(f"[OpenApp] 🎮 Lanzando juego desde {_GAME_DIR}")

    # Verificar que el ejecutable existe antes de intentar correrlo
    game_path = os.path.join(_GAME_DIR, "JuegoFinalV2.arm64")
    if not os.path.exists(game_path):
        msg = f"No encontré el juego en {game_path}. Asegúrate de que JuegoFinalV2.arm64 esté en el Desktop."
        print(f"[OpenApp] ❌ {msg}")
        return f"juego_no_encontrado: {msg}"

    try:
        subprocess.Popen(
            [_GAME_BIN] + _GAME_ARGS,
            cwd=_GAME_DIR,
            # No bloquea — el juego corre en segundo plano
        )
        print("[OpenApp] ✅ Juego lanzado correctamente.")
        return "juego_iniciado: JuegoFinalV2 abierto en pantalla completa."

    except Exception as exc:
        print(f"[OpenApp] ❌ Error al lanzar el juego: {exc}")
        return f"error_al_abrir_juego: {exc}"
