"""
ui/audio_input.py – STT con speech_recognition + Google STT.

Modo siempre activo (sin wake word):
  - Escucha continuamente sin requerir nombre de activación.
  - Anti-eco por timestamp: descarta audio captado mientras NARONA habla.
  - Al captar entrada válida, reproduce SonidoNoti.mp3 como confirmación
    auditiva antes de procesar el comando.
"""

import json
import os
import threading
import time

import speech_recognition as sr

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    STT_LANGUAGE: str            = _cfg.get("stt_language",              "es-ES")
    _SILENCE_AFTER_SPEECH: float = float(_cfg.get("stt_silence_after_speech", 1.0))
    _CMD_TIMEOUT: int            = int(_cfg.get("stt_cmd_timeout",       8))
    _CMD_PHRASE_LIMIT: int       = int(_cfg.get("stt_cmd_phrase_limit",  12))
except Exception:
    STT_LANGUAGE          = "es-ES"
    _SILENCE_AFTER_SPEECH = 1.0
    _CMD_TIMEOUT          = 8
    _CMD_PHRASE_LIMIT     = 12

_recognizer = sr.Recognizer()
_recognizer.pause_threshold          = 1.0
_recognizer.energy_threshold         = 300
_recognizer.dynamic_energy_threshold = True


# ---------------------------------------------------------------------------
# STT interno
# ---------------------------------------------------------------------------

def _stt_once(timeout: int, phrase_limit: int) -> str:
    """Escucha y reconoce audio. Devuelve str vacío si no hay habla o hay error."""
    with sr.Microphone() as source:
        _recognizer.adjust_for_ambient_noise(source, duration=0.4)
        try:
            audio = _recognizer.listen(
                source, timeout=timeout, phrase_time_limit=phrase_limit
            )
        except sr.WaitTimeoutError:
            return ""
    try:
        return _recognizer.recognize_google(audio, language=STT_LANGUAGE).strip()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as exc:
        print(f"[audio_input] Error STT: {exc}")
        return ""


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def listen_once(timeout: int = 8, phrase_limit: int = 10) -> str:
    """Escucha un fragmento y devuelve el texto reconocido."""
    return _stt_once(timeout, phrase_limit)


def listen_loop(callback, stop_event: threading.Event) -> None:
    """Escucha continuamente y llama a *callback(text)* por cada utterance válido.

    Anti-eco (pre-check):
      - Espera a que `is_speaking` se limpie antes de abrir el micrófono.
      - Verifica también `_last_speech_end` ANTES de escuchar. Si todavía
        estamos en el margen de eco, espera sin abrir el mic.
      - Tras grabar, hace un check final por si el TTS arrancó durante la grabación.

    Feedback auditivo:
      - SonidoNoti.mp3 se reproduce JUSTO ANTES de que el micrófono se abra,
        funcionando como señal de "mic activado, puedes hablar".

    Args:
        callback:   función invocada con el texto reconocido (str).
        stop_event: cuando se activa, el bucle termina limpiamente.
    """
    import ui.audio_output as _ao
    from ui.wake_word import play_notification_sound

    while not stop_event.is_set():

        # ── 1. Esperar a que NARONA termine de hablar ────────────────────────
        if _ao.is_speaking.is_set():
            _ao.is_speaking.wait(timeout=30)
            time.sleep(_SILENCE_AFTER_SPEECH)
            continue

        # ── 2. Pre-check anti-eco (ANTES de abrir el micrófono) ─────────────
        # Si todavía estamos dentro del margen posterior al TTS, no abrimos mic.
        now = time.time()
        safe_resume = _ao._last_speech_end + _SILENCE_AFTER_SPEECH
        if now < safe_resume:
            time.sleep(0.1)   # esperar en pequeños pasos hasta que pase el margen
            continue

        # ── 3. 🔔 Sonido de activación → micrófono a punto de abrirse ────────
        play_notification_sound()

        # ── 4. Escuchar ──────────────────────────────────────────────────────
        listen_start = time.time()
        text = _stt_once(timeout=_CMD_TIMEOUT, phrase_limit=_CMD_PHRASE_LIMIT)

        if not text:
            continue

        # ── 5. Check post-grabación: ¿arrancó TTS mientras escuchábamos? ─────
        if _ao.is_speaking.is_set():
            print(f"[audio_input] ⚠️  TTS activo durante grabación, descartando: {text!r}")
            continue

        # Si NARONA habló Y terminó durante la grabación, _last_speech_end
        # será mayor que listen_start → descartar también ese caso.
        if listen_start < (_ao._last_speech_end + _SILENCE_AFTER_SPEECH):
            print(f"[audio_input] ⚠️  TTS ocurrió durante grabación, descartando: {text!r}")
            continue

        # ── 6. Entrada válida → enviar al agente ─────────────────────────────
        print(f"[audio_input] ✅ Captado: {text!r}")
        callback(text)
