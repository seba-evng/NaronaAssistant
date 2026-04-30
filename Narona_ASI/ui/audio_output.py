"""
ui/audio_output.py - TTS con edge-tts (voz neural) + fallback pyttsx3.

Modos:
  speak()       → edge-tts con timeout de 5s. Si falla/tarda → pyttsx3 automático.
  speak_local() → pyttsx3 directo (sin internet). Usar en despedida/apagado.
  speak_async() → llama a speak() en un hilo separado.
"""

import json
import os
import queue
import tempfile
import threading
import time

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    _TTS_RATE: int     = int(_cfg.get("tts_rate",     145))
    _TTS_VOLUME: float = float(_cfg.get("tts_volume", 1.0))
    _TTS_LANGUAGE: str = _cfg.get("tts_language",     "es")
    _TTS_VOICE: str    = _cfg.get("tts_voice",        "es-MX-DaliaNeural")
except Exception:
    _TTS_RATE     = 145
    _TTS_VOLUME   = 1.0
    _TTS_LANGUAGE = "es"
    _TTS_VOICE    = "es-MX-DaliaNeural"

# Tiempo máximo de espera para síntesis cloud.
# Si Microsoft tarda más de esto → fallback instantáneo a pyttsx3.
_EDGE_TIMEOUT: float = 5.0

is_speaking: threading.Event = threading.Event()
_last_speech_end: float = 0.0

_USE_EDGE_TTS = False
try:
    import edge_tts   # noqa: F401
    import asyncio    # noqa: F401
    import pygame     # noqa: F401

    _USE_EDGE_TTS = True
    print("[TTS] edge-tts + pygame disponibles -> usando voz neural")
except ImportError:
    print("[TTS] edge-tts/pygame no instalados -> usando pyttsx3 como fallback")

_tts_queue: queue.Queue = queue.Queue()


# ---------------------------------------------------------------------------
# Selección de voz pyttsx3
# ---------------------------------------------------------------------------

def _select_pyttsx3_voice(engine) -> None:
    """Selecciona la mejor voz en español disponible en pyttsx3."""
    voices = engine.getProperty("voices")

    for voice in voices:
        vid  = (voice.id   or "").lower()
        vnam = (voice.name or "").lower()
        if (("es" in vid or "spanish" in vid or "espanol" in vnam) and
                ("female" in vid or "zira" in vid or "sabina" in vnam
                 or "helena" in vnam or "lucia" in vnam or "paulina" in vnam)):
            engine.setProperty("voice", voice.id)
            print(f"[TTS] Voz femenina española: {voice.name}")
            return

    for voice in voices:
        vid  = (voice.id   or "").lower()
        vnam = (voice.name or "").lower()
        if _TTS_LANGUAGE in vid or "spanish" in vid or "espanol" in vnam:
            engine.setProperty("voice", voice.id)
            print(f"[TTS] Voz española: {voice.name}")
            return

    for voice in voices:
        vid  = (voice.id   or "").lower()
        if "female" in vid or "zira" in vid:
            engine.setProperty("voice", voice.id)
            print(f"[TTS] Voz femenina alternativa: {voice.name}")
            return

    print("[TTS] Usando voz por defecto del sistema")


# ---------------------------------------------------------------------------
# Worker pyttsx3 (hilo dedicado, siempre en ejecución)
# ---------------------------------------------------------------------------

def _pyttsx3_worker() -> None:
    """Hilo dedicado al motor pyttsx3."""
    import pyttsx3

    engine = pyttsx3.init()
    engine.setProperty("rate",   _TTS_RATE)
    engine.setProperty("volume", _TTS_VOLUME)
    _select_pyttsx3_voice(engine)

    while True:
        text = _tts_queue.get()
        if text is None:
            break
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            print(f"[TTS] Error pyttsx3: {exc}")
        finally:
            _tts_queue.task_done()


_pyttsx3_thread = threading.Thread(
    target=_pyttsx3_worker, daemon=True, name="tts-pyttsx3-worker"
)
_pyttsx3_thread.start()


# ---------------------------------------------------------------------------
# Backends TTS
# ---------------------------------------------------------------------------

def _speak_edge(text: str) -> None:
    """
    Sintetiza con edge-tts (cloud) y reproduce con pygame.

    Si la síntesis tarda más de _EDGE_TIMEOUT segundos, cancela y cae a pyttsx3.
    El event loop se cierra siempre en el bloque finally para evitar leaks.
    """
    import asyncio
    import pygame

    async def _synth(path: str) -> None:
        import edge_tts
        communicate = edge_tts.Communicate(text, _TTS_VOICE)
        # wait_for lanza asyncio.TimeoutError si supera el límite
        await asyncio.wait_for(communicate.save(path), timeout=_EDGE_TIMEOUT)

    tmp_path = None
    loop = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_synth(tmp_path))

        # Reproducción con pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100)
        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.set_volume(_TTS_VOLUME)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.stop()

    except asyncio.TimeoutError:
        print(
            f"[TTS] ⏱️  edge-tts timeout ({_EDGE_TIMEOUT}s) "
            "→ cambiando a pyttsx3 instantáneamente"
        )
        _speak_pyttsx3(text)

    except Exception as exc:
        print(f"[TTS] edge-tts falló ({exc}) → usando pyttsx3")
        _speak_pyttsx3(text)

    finally:
        # Siempre cerrar el loop aunque haya excepción
        if loop and not loop.is_closed():
            loop.close()
        # Limpiar archivo temporal
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _speak_pyttsx3(text: str) -> None:
    """Encola texto en el hilo pyttsx3 dedicado y espera a que termine."""
    _tts_queue.put(text)
    _tts_queue.join()


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def speak(text: str) -> None:
    """
    Reproduce texto por el altavoz de forma bloqueante.
    Usa edge-tts si está disponible; si tarda > 5s cae automáticamente a pyttsx3.
    """
    global _last_speech_end
    if not text:
        return

    is_speaking.set()
    try:
        if _USE_EDGE_TTS:
            _speak_edge(text)
        else:
            _speak_pyttsx3(text)
    finally:
        _last_speech_end = time.time()
        is_speaking.clear()


def speak_local(text: str) -> None:
    """
    Reproduce texto usando SOLO pyttsx3 (sin internet).

    Usar en mensajes de despedida o apagado donde no hay garantía de conexión
    y no queremos esperar el timeout de edge-tts antes de cerrar el programa.
    """
    global _last_speech_end
    if not text:
        return

    is_speaking.set()
    try:
        _speak_pyttsx3(text)
    finally:
        _last_speech_end = time.time()
        is_speaking.clear()


def speak_async(text: str) -> threading.Thread:
    """Reproduce texto en un hilo separado y devuelve el Thread."""
    thread = threading.Thread(target=speak, args=(text,), daemon=True)
    thread.start()
    return thread
