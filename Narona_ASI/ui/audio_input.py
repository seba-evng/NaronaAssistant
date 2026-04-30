"""
ui/audio_input.py - STT con speech_recognition + Google STT.

Modo siempre activo:
  - Escucha continuamente sin requerir wake word.
  - Anti-eco por timestamp: descarta audio captado mientras NARONA habla.
  - Reproduce SonidoNoti.mp3 justo antes de abrir el microfono.
"""

import json
import os
import threading
import time

import speech_recognition as sr


_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    STT_LANGUAGE: str = _cfg.get("stt_language", "es-ES")
    _SILENCE_AFTER_SPEECH: float = float(_cfg.get("stt_silence_after_speech", 1.0))
    _CMD_TIMEOUT: int = int(_cfg.get("stt_cmd_timeout", 8))
    _CMD_PHRASE_LIMIT: int = int(_cfg.get("stt_cmd_phrase_limit", 12))
except Exception:
    STT_LANGUAGE = "es-ES"
    _SILENCE_AFTER_SPEECH = 1.0
    _CMD_TIMEOUT = 8
    _CMD_PHRASE_LIMIT = 12

_recognizer = sr.Recognizer()
_recognizer.pause_threshold = 1.0
_recognizer.energy_threshold = 300
_recognizer.dynamic_energy_threshold = True


def _stt_once(timeout: int, phrase_limit: int) -> str:
    """Escucha y reconoce audio. Devuelve str vacio si no hay habla o hay error."""
    with sr.Microphone() as source:
        _recognizer.adjust_for_ambient_noise(source, duration=0.4)
        try:
            audio = _recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_limit,
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


def _wait_until_microphone_ready(play_notification: bool = False) -> None:
    """Espera a que el TTS termine y el microfono pueda abrirse sin eco."""
    import ui.audio_output as _ao

    while True:
        if _ao.is_speaking.is_set():
            _ao.is_speaking.wait(timeout=30)
            time.sleep(_SILENCE_AFTER_SPEECH)
            continue

        safe_resume = _ao._last_speech_end + _SILENCE_AFTER_SPEECH
        if time.time() < safe_resume:
            time.sleep(0.1)
            continue

        if play_notification:
            from ui.wake_word import play_notification_sound

            play_notification_sound()
        return


def listen_once(timeout: int = 8, phrase_limit: int = 10, notify: bool = False) -> str:
    """Escucha un fragmento y devuelve el texto reconocido."""
    _wait_until_microphone_ready(play_notification=notify)
    return _stt_once(timeout, phrase_limit)


def listen_loop(callback, stop_event: threading.Event) -> None:
    """Escucha continuamente y llama a callback(text) por cada entrada valida."""
    import ui.audio_output as _ao

    while not stop_event.is_set():
        _wait_until_microphone_ready(play_notification=True)

        listen_start = time.time()
        text = _stt_once(timeout=_CMD_TIMEOUT, phrase_limit=_CMD_PHRASE_LIMIT)

        if not text:
            continue

        if _ao.is_speaking.is_set():
            print(f"[audio_input] TTS activo durante grabacion, descartando: {text!r}")
            continue

        if listen_start < (_ao._last_speech_end + _SILENCE_AFTER_SPEECH):
            print(f"[audio_input] TTS ocurrio durante grabacion, descartando: {text!r}")
            continue

        print(f"[audio_input] Captado: {text!r}")
        callback(text)
