"""
ui/audio_output.py – TTS con pyttsx3.
Voz en español, velocidad 140 wpm, adecuada para niños.
"""

import json
import os
import threading

import pyttsx3

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    _TTS_RATE: int = int(_cfg.get("tts_rate", 140))
    _TTS_VOLUME: float = float(_cfg.get("tts_volume", 1.0))
    _TTS_LANGUAGE: str = _cfg.get("tts_language", "es")
except Exception:
    _TTS_RATE = 140
    _TTS_VOLUME = 1.0
    _TTS_LANGUAGE = "es"

# ---------------------------------------------------------------------------
# Motor TTS (instancia global)
# ---------------------------------------------------------------------------

def _build_engine() -> pyttsx3.Engine:
    engine = pyttsx3.init()
    engine.setProperty("rate", _TTS_RATE)
    engine.setProperty("volume", _TTS_VOLUME)
    # Intentar seleccionar voz en español
    voices = engine.getProperty("voices")
    for voice in voices:
        if _TTS_LANGUAGE in (voice.id or "").lower() or _TTS_LANGUAGE in (voice.name or "").lower():
            engine.setProperty("voice", voice.id)
            break
    return engine


_engine_lock = threading.Lock()
_engine: pyttsx3.Engine = _build_engine()


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def speak(text: str) -> None:
    """Reproduce *text* por el altavoz de forma bloqueante."""
    with _engine_lock:
        _engine.say(text)
        _engine.runAndWait()


def speak_async(text: str) -> threading.Thread:
    """Reproduce *text* en un hilo separado y devuelve el Thread."""
    t = threading.Thread(target=speak, args=(text,), daemon=True)
    t.start()
    return t
