"""
ui/audio_output.py – TTS con pyttsx3.
Voz en español, velocidad 160 wpm, adecuada para niños.
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
    _TTS_RATE: int = int(_cfg.get("tts_rate", 160))
    _TTS_VOLUME: float = float(_cfg.get("tts_volume", 1.0))
    _TTS_LANGUAGE: str = _cfg.get("tts_language", "es")
except Exception:
    _TTS_RATE = 160
    _TTS_VOLUME = 1.0
    _TTS_LANGUAGE = "es"

# ---------------------------------------------------------------------------
# Motor TTS (instancia global)
# ---------------------------------------------------------------------------

def _build_engine() -> pyttsx3.Engine:
    engine = pyttsx3.init()
    engine.setProperty("rate", _TTS_RATE)
    engine.setProperty("volume", _TTS_VOLUME)

    voices = engine.getProperty("voices")

    # Diagnóstico: mostrar voces disponibles
    print("[TTS] Voces disponibles:")
    for v in voices:
        print(f"  - {v.id}  |  {v.name}")

    # Prioridad 1: voz femenina en español (más amigable para niños)
    for voice in voices:
        vid   = (voice.id   or "").lower()
        vname = (voice.name or "").lower()
        if ("es" in vid or "spanish" in vid or "español" in vname or "es" in vname) and \
           ("female" in vid or "zira" in vid or "sabina" in vname or "helena" in vname or "lucia" in vname):
            engine.setProperty("voice", voice.id)
            print(f"[TTS] ✅ Voz femenina española seleccionada: {voice.name}")
            return engine

    # Prioridad 2: cualquier voz en español
    for voice in voices:
        vid   = (voice.id   or "").lower()
        vname = (voice.name or "").lower()
        if _TTS_LANGUAGE in vid or "spanish" in vid or "español" in vname:
            engine.setProperty("voice", voice.id)
            print(f"[TTS] ✅ Voz española seleccionada: {voice.name}")
            return engine

    # Prioridad 3: voz femenina en cualquier idioma
    for voice in voices:
        vid = (voice.id or "").lower()
        if "female" in vid or "zira" in vid or "female" in (voice.name or "").lower():
            engine.setProperty("voice", voice.id)
            print(f"[TTS] ℹ️ Voz femenina seleccionada: {voice.name}")
            return engine

    print("[TTS] ⚠️ Usando voz por defecto")
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
