"""
ui/wake_word.py – Reproductor de sonido de notificación.

Reproduce Assets/SonidoNoti.mp3 cuando NARONA capta una entrada válida
del usuario, antes de procesarla. Usa pygame (ya instalado).

Si el archivo no existe o hay un error, falla silenciosamente para no
interrumpir el flujo del asistente.
"""

import os
import time

# Ruta al archivo de sonido
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "Assets")
_SOUND_PATH = os.path.abspath(os.path.join(_ASSETS_DIR, "SonidoNoti.mp3"))


def play_notification_sound() -> None:
    """Reproduce SonidoNoti.mp3 de la carpeta Assets de forma bloqueante.

    Bloqueante: espera a que termine el sonido antes de continuar,
    para que el usuario sepa que NARONA captó su voz antes de responder.
    """
    if not os.path.isfile(_SOUND_PATH):
        print(f"[sound] ⚠️  Archivo no encontrado: {_SOUND_PATH}")
        return

    try:
        import pygame

        # Inicializar mixer si no está activo
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100)

        # Usar un Canal dedicado para no interferir con pygame.mixer.music (TTS)
        sound = pygame.mixer.Sound(_SOUND_PATH)
        sound.set_volume(0.75)
        channel = sound.play()

        # Esperar a que termine
        if channel:
            while channel.get_busy():
                time.sleep(0.02)

    except Exception as exc:
        print(f"[sound] Error reproduciendo SonidoNoti.mp3: {exc}")
