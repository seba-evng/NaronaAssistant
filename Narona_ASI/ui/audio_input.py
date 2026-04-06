"""
ui/audio_input.py – STT con speech_recognition + Google STT.
"""

import json
import os
import threading

import speech_recognition as sr

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    STT_LANGUAGE: str = _cfg.get("stt_language", "es-ES")
except Exception:
    STT_LANGUAGE = "es-ES"

_recognizer = sr.Recognizer()
_recognizer.pause_threshold = 1.0
_recognizer.energy_threshold = 300


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def listen_once(timeout: int = 8, phrase_limit: int = 10) -> str:
    """Escucha un fragmento de audio y devuelve el texto reconocido.

    Args:
        timeout: segundos máximos esperando que comience el habla.
        phrase_limit: duración máxima de la frase en segundos.

    Returns:
        Texto reconocido o cadena vacía si hubo error.
    """
    with sr.Microphone() as source:
        _recognizer.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = _recognizer.listen(
                source, timeout=timeout, phrase_time_limit=phrase_limit
            )
        except sr.WaitTimeoutError:
            return ""

    try:
        text = _recognizer.recognize_google(audio, language=STT_LANGUAGE)
        return text.strip()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as exc:
        print(f"[audio_input] Error de red STT: {exc}")
        return ""


def listen_loop(callback, stop_event: threading.Event) -> None:
    """Escucha continuamente y llama a *callback(text)* por cada utterance.

    Args:
        callback: función invocada con el texto reconocido (str).
        stop_event: evento de threading; cuando se activa, el bucle termina.
    """
    while not stop_event.is_set():
        text = listen_once()
        if text:
            callback(text)
