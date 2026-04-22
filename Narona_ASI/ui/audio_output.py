"""
ui/audio_output.py – TTS con edge-tts (voz neural) + fallback pyttsx3.

Correcciones:
  1. Hilo TTS dedicado → evita el cuelgue de pyttsx3 en Windows tras varias llamadas.
  2. Flag `is_speaking` → audio_input lo lee para silenciar el micrófono mientras
     NARONA habla, previniendo el bucle de auto-escucha.
  3. edge-tts como backend primario → voz neural más natural y amigable.
     Si no está instalado, cae a pyttsx3 automáticamente.
"""

import json
import os
import queue
import tempfile
import threading
import time

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    _TTS_RATE: int   = int(_cfg.get("tts_rate", 145))
    _TTS_VOLUME: float = float(_cfg.get("tts_volume", 1.0))
    _TTS_LANGUAGE: str = _cfg.get("tts_language", "es")
    # Voz neural preferida (edge-tts). Puedes cambiarla en api_keys.json
    # Opciones recomendadas:
    #   "es-MX-DaliaNeural"   ← México, muy amigable  ✅ (default)
    #   "es-ES-ElviraNeural"  ← España
    #   "es-AR-ElenaNeural"   ← Argentina
    _TTS_VOICE: str = _cfg.get("tts_voice", "es-MX-DaliaNeural")
except Exception:
    _TTS_RATE     = 145
    _TTS_VOLUME   = 1.0
    _TTS_LANGUAGE = "es"
    _TTS_VOICE    = "es-MX-DaliaNeural"

# ---------------------------------------------------------------------------
# Flags globales para anti-eco:
#   is_speaking        → True mientras el TTS está activo
#   _last_speech_end   → timestamp float de cuando terminó el ÚLTIMO speak()
# audio_input.py importa ambos para comparar con el inicio de cada grabación.
# ---------------------------------------------------------------------------
is_speaking: threading.Event = threading.Event()
_last_speech_end: float = 0.0   # se actualiza al final de cada speak()

# ---------------------------------------------------------------------------
# Detección del backend disponible
# ---------------------------------------------------------------------------
_USE_EDGE_TTS = False
try:
    import edge_tts          # noqa: F401  (solo para verificar)
    import asyncio           # noqa: F401
    import pygame            # noqa: F401
    _USE_EDGE_TTS = True
    print("[TTS] ✅ edge-tts + pygame disponibles – usando voz neural")
except ImportError:
    print("[TTS] ℹ️  edge-tts/pygame no instalados – usando pyttsx3 como fallback")

# ---------------------------------------------------------------------------
# Backend pyttsx3 – hilo dedicado (fix para Windows SAPI5)
# ---------------------------------------------------------------------------
_tts_queue: queue.Queue = queue.Queue()


def _select_pyttsx3_voice(engine) -> None:
    """Selecciona la mejor voz en español disponible en pyttsx3."""
    voices = engine.getProperty("voices")
    print("[TTS] Voces disponibles (pyttsx3):")
    for v in voices:
        print(f"  - {v.id}  |  {v.name}")

    # Prioridad 1: voz femenina en español
    for voice in voices:
        vid   = (voice.id   or "").lower()
        vname = (voice.name or "").lower()
        if ("es" in vid or "spanish" in vid or "español" in vname) and \
           ("female" in vid or "zira" in vid or "sabina" in vname or
            "helena" in vname or "lucia" in vname or "paulina" in vname):
            engine.setProperty("voice", voice.id)
            print(f"[TTS] ✅ Voz femenina española: {voice.name}")
            return

    # Prioridad 2: cualquier voz en español
    for voice in voices:
        vid   = (voice.id   or "").lower()
        vname = (voice.name or "").lower()
        if _TTS_LANGUAGE in vid or "spanish" in vid or "español" in vname:
            engine.setProperty("voice", voice.id)
            print(f"[TTS] ✅ Voz española: {voice.name}")
            return

    # Prioridad 3: voz femenina en cualquier idioma
    for voice in voices:
        vid   = (voice.id   or "").lower()
        vname = (voice.name or "").lower()
        if "female" in vid or "zira" in vid or "female" in vname:
            engine.setProperty("voice", voice.id)
            print(f"[TTS] ℹ️  Voz femenina (sin español): {voice.name}")
            return

    print("[TTS] ⚠️  Usando voz por defecto del sistema")


def _pyttsx3_worker() -> None:
    """
    Hilo dedicado al motor pyttsx3.

    Motivo: en Windows (SAPI5) el event-loop interno de pyttsx3 debe correr
    siempre en el mismo hilo donde se inicializó el engine. Si se llama
    runAndWait() desde hilos distintos el engine deja de funcionar tras la
    primera llamada. Al mantener un único hilo dedicado este problema desaparece.
    """
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate",   _TTS_RATE)
    engine.setProperty("volume", _TTS_VOLUME)
    _select_pyttsx3_voice(engine)

    while True:
        text = _tts_queue.get()
        if text is None:          # señal de parada
            break
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            print(f"[TTS] Error pyttsx3: {exc}")
        finally:
            _tts_queue.task_done()


# Iniciar hilo pyttsx3 siempre (sirve como fallback aunque edge-tts esté disponible)
_pyttsx3_thread = threading.Thread(
    target=_pyttsx3_worker, daemon=True, name="tts-pyttsx3-worker"
)
_pyttsx3_thread.start()

# ---------------------------------------------------------------------------
# Funciones internas de síntesis
# ---------------------------------------------------------------------------

def _speak_edge(text: str) -> None:
    """Sintetiza con edge-tts y reproduce con pygame."""
    import asyncio
    import pygame

    async def _synth(path: str) -> None:
        import edge_tts
        communicate = edge_tts.Communicate(text, _TTS_VOICE)
        await communicate.save(path)

    tmp_path = None
    try:
        # Generar audio en archivo temporal
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_synth(tmp_path))
        loop.close()

        # Reproducir con pygame – mixer se inicializa una sola vez y nunca se cierra
        # para no interferir con los beeps de wake_word.py (que usan winsound).
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100)
        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.set_volume(_TTS_VOLUME)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.stop()
        # ⚠️  NO llamar pygame.mixer.quit() — lo mantiene disponible para reutilizar

    except Exception as exc:
        print(f"[TTS] edge-tts falló ({exc}) → usando pyttsx3")
        _speak_pyttsx3(text)
    finally:
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
# Funciones públicas
# ---------------------------------------------------------------------------

def speak(text: str) -> None:
    """
    Reproduce *text* por el altavoz de forma bloqueante.

    Activa `is_speaking` al inicio y lo limpia al terminar.
    También actualiza `_last_speech_end` con el timestamp de finalización para
    que audio_input pueda descartar grabaciones que hayan solapado con TTS.
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
        import time as _time
        _last_speech_end = _time.time()
        is_speaking.clear()


def speak_async(text: str) -> threading.Thread:
    """Reproduce *text* en un hilo separado y devuelve el Thread."""
    t = threading.Thread(target=speak, args=(text,), daemon=True)
    t.start()
    return t
