"""
ui/command_interceptor.py – Detecta y ejecuta comandos simples localmente.

Ventaja: evita consumir tokens de la API para peticiones triviales.
Python detecta la intención con regex y ejecuta la acción directamente.

Interceptores disponibles:
  ✅ Abrir apps          → "abre Chrome", "abre YouTube"
  ✅ Cerrar apps         → "cierra Chrome", "cierra Spotify"
  ✅ Hora y fecha        → "¿qué hora es?", "¿qué día es hoy?"
  ✅ Volumen             → "sube el volumen", "baja el volumen", "silencia"
  ✅ Feedback confianza  → si el nombre de la app es ambiguo, pregunta antes de abrir

Para añadir nuevos interceptores, agrega una sección al final de try_intercept().
"""

import difflib
import re
import subprocess
import ctypes
from datetime import datetime
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Alias voz → nombre canónico de app
# ---------------------------------------------------------------------------
_VOICE_ALIASES: dict[str, str] = {
    # Navegadores
    "chrome":                   "chrome",
    "google":                   "chrome",
    "google chrome":            "chrome",
    "firefox":                  "firefox",
    "mozilla":                  "firefox",
    "edge":                     "msedge",
    "microsoft edge":           "msedge",
    "brave":                    "brave",

    # Redes sociales / mensajería
    "whatsapp":                 "whatsapp",
    "watsapp":                  "whatsapp",
    "telegram":                 "telegram",
    "discord":                  "discord",
    "zoom":                     "zoom",

    # Entretenimiento
    "youtube":                  "youtube",
    "netflix":                  "netflix",
    "spotify":                  "spotify",
    "vlc":                      "vlc",
    "twitch":                   "twitch",

    # Ofimática
    "word":                     "word",
    "excel":                    "excel",
    "powerpoint":               "powerpoint",
    "power point":              "powerpoint",
    "teams":                    "teams",
    "outlook":                  "outlook",

    # Sistema
    "notepad":                  "notepad",
    "bloc de notas":            "notepad",
    "bloc":                     "notepad",
    "calculadora":              "calculadora",
    "calculator":               "calculadora",
    "paint":                    "paint",
    "explorador":               "explorer",
    "explorador de archivos":   "explorer",
    "administrador de tareas":  "administrador de tareas",
    "task manager":             "administrador de tareas",
    "configuración":            "ms-settings:",
    "configuracion":            "ms-settings:",
    "ajustes":                  "ms-settings:",

    # Juegos / otros
    "minecraft":                "minecraft",
    "roblox":                   "roblox",
    "steam":                    "steam",
    "epic":                     "epicgameslauncher",
    "epic games":               "epicgameslauncher",
    "fortnite":                 "com.epicgames.launcher://apps/fortnite",
}

# Procesos de sistema para cerrar (app canónica → nombre del .exe)
_EXE_MAP: dict[str, str] = {
    "chrome":                   "chrome.exe",
    "firefox":                  "firefox.exe",
    "msedge":                   "msedge.exe",
    "brave":                    "brave.exe",
    "spotify":                  "spotify.exe",
    "discord":                  "discord.exe",
    "zoom":                     "zoom.exe",
    "teams":                    "teams.exe",
    "outlook":                  "outlook.exe",
    "notepad":                  "notepad.exe",
    "vlc":                      "vlc.exe",
    "steam":                    "steam.exe",
    "minecraft":                "javaw.exe",
    "word":                     "winword.exe",
    "excel":                    "excel.exe",
    "powerpoint":               "powerpnt.exe",
}

# Respuestas amigables para abrir
_OPEN_REPLIES = [
    "¡Claro! Abriendo {app} ahora mismo. 🚀",
    "¡Listo! Abro {app} para ti.",
    "¡Vamos! Arrancando {app}.",
    "¡Ya va! Abro {app}.",
]
# Respuestas para cerrar
_CLOSE_REPLIES = [
    "Cerrando {app}. ¡Hasta luego, {app}!",
    "¡Listo! Cerré {app}.",
    "¡Hecho! {app} ya está cerrada.",
]
_reply_index = 0


def _pick(replies: list, app: str) -> str:
    global _reply_index
    r = replies[_reply_index % len(replies)].format(app=app)
    _reply_index += 1
    return r


# ---------------------------------------------------------------------------
# Patrones regex
# ---------------------------------------------------------------------------
_OPEN_PATTERN = re.compile(
    r"""
    (?:(?:por\s+favor[\s,]+)?(?:p[uo]edes?\s+)?(?:anda\s+)?)
    abr(?:e|ir|í|eme|enos|ete)\s+
    (?:el\s+|la\s+|los\s+|las\s+|un\s+|una\s+)?
    (?P<app>.+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_CLOSE_PATTERN = re.compile(
    r"""
    (?:(?:por\s+favor[\s,]+)?(?:p[uo]edes?\s+)?)
    (?:cierra|cerrar|cierre|mata|termina|apaga)\s+
    (?:el\s+|la\s+|los\s+|las\s+)?
    (?P<app>.+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_TIME_PATTERN = re.compile(
    r"(?:qu[eé]\s+hora|dime\s+la\s+hora|cu[aá]nto\s+son|qu[eé]\s+horas?)",
    re.IGNORECASE,
)

_DATE_PATTERN = re.compile(
    r"(?:qu[eé]\s+d[ií]a|qu[eé]\s+fecha|hoy\s+es|cu[aá]ndo\s+es|fecha\s+(?:de\s+)?hoy)",
    re.IGNORECASE,
)

_VOL_UP_PATTERN = re.compile(
    r"(?:sube|aumenta|pon\s+más|más)\s+(?:el\s+)?volumen",
    re.IGNORECASE,
)

_VOL_DOWN_PATTERN = re.compile(
    r"(?:baja|reduce|pon\s+menos|menos)\s+(?:el\s+)?volumen",
    re.IGNORECASE,
)

_MUTE_PATTERN = re.compile(
    r"(?:silencia|silencio|cállate|mute|quita\s+el\s+sonido|sin\s+sonido)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers de volumen (Windows, sin pip)
# ---------------------------------------------------------------------------
_VK_VOLUME_UP   = 0xAF
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_MUTE = 0xAD


def _press_key(vk: int) -> None:
    """Simula una pulsación de tecla multimedia en Windows."""
    try:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    except Exception as exc:
        print(f"[Interceptor] ⚠️  keybd_event error: {exc}")


def _adjust_volume(steps: int = 3) -> None:
    """Sube o baja el volumen del sistema. steps negativo = bajar."""
    vk = _VK_VOLUME_UP if steps > 0 else _VK_VOLUME_DOWN
    for _ in range(abs(steps)):
        _press_key(vk)


# ---------------------------------------------------------------------------
# Resolución de nombre de app + feedback de confianza
# ---------------------------------------------------------------------------

def _resolve_app(raw: str) -> tuple[Optional[str], float]:
    """
    Normaliza el nombre de app extraído por el regex.

    Returns:
        (canonical_name, confidence)
        confidence: 1.0 = alias exacto, 0.7-0.9 = fuzzy match, 0.0 = no encontrado
    """
    raw = raw.strip().rstrip(".,!?")
    lower = raw.lower()

    # Exacto
    if lower in _VOICE_ALIASES:
        return _VOICE_ALIASES[lower], 1.0

    # Alias contenido en lo dicho ("ábreme el google chrome por favor")
    for alias, canonical in _VOICE_ALIASES.items():
        if alias in lower:
            return canonical, 0.95

    # Fuzzy match contra todos los alias
    all_aliases = list(_VOICE_ALIASES.keys())
    matches = difflib.get_close_matches(lower, all_aliases, n=1, cutoff=0.6)
    if matches:
        best = matches[0]
        ratio = difflib.SequenceMatcher(None, lower, best).ratio()
        return _VOICE_ALIASES[best], round(ratio, 2)

    # No encontrado → devolver tal como vino (open_app intentará igual)
    return raw if raw else None, 0.0


def _confirm_with_user(
    question: str,
    speak: Callable[[str], None],
    listen_fn: Optional[Callable[[], str]] = None,
) -> bool:
    """
    Hace una pregunta de sí/no y espera respuesta del usuario.
    Devuelve True si el usuario dice que sí.
    """
    speak(question)

    if listen_fn is None:
        # Importación local para no crear ciclos
        from ui.audio_input import listen_once
        listen_fn = lambda: listen_once(timeout=5, phrase_limit=4)

    answer = listen_fn()
    print(f"[Interceptor] Respuesta confirmación: {answer!r}")
    yes_words = {"sí", "si", "yes", "dale", "claro", "ok", "okay", "por favor",
                 "ábrelo", "abrelo", "adelante", "correcto", "exacto"}
    return any(w in answer.lower() for w in yes_words)


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

def try_intercept(text: str, speak: Callable[[str], None]) -> bool:
    """Intenta manejar *text* localmente sin usar la API.

    Returns:
        True  → comando interceptado (NO llamar al LLM).
        False → no reconocido, llamar al LLM normalmente.
    """

    # ══════════════════════════════════════════════════════════════════════
    # 1. ABRIR APLICACIÓN
    # ══════════════════════════════════════════════════════════════════════
    m = _OPEN_PATTERN.search(text)
    if m:
        app_raw  = m.group("app")
        app_name, confidence = _resolve_app(app_raw)

        if app_name:
            print(f"[Interceptor] 🎯 Abrir '{app_name}' (confianza: {confidence:.0%})")

            # Confianza media → preguntar antes de abrir
            if 0.5 <= confidence < 0.85:
                friendly = app_name.capitalize()
                confirmed = _confirm_with_user(
                    f"¿Quisiste decir {friendly}? Dime sí o no.",
                    speak,
                )
                if not confirmed:
                    speak("Está bien, dime qué quieres abrir y lo hago.")
                    return True   # interceptado (evitamos LLM pero no abrimos)

            from actions.open_app import open_app
            open_app({"app_name": app_name}, None, None)
            speak(_pick(_OPEN_REPLIES, app_name.capitalize()))
            return True

    # ══════════════════════════════════════════════════════════════════════
    # 2. CERRAR APLICACIÓN
    # ══════════════════════════════════════════════════════════════════════
    m = _CLOSE_PATTERN.search(text)
    if m:
        app_raw  = m.group("app")
        app_name, confidence = _resolve_app(app_raw)

        if app_name:
            print(f"[Interceptor] 🎯 Cerrar '{app_name}' (confianza: {confidence:.0%})")

            if 0.5 <= confidence < 0.85:
                confirmed = _confirm_with_user(
                    f"¿Quieres que cierre {app_name.capitalize()}?",
                    speak,
                )
                if not confirmed:
                    speak("De acuerdo, no cierro nada.")
                    return True

            # Obtener nombre del .exe
            exe = _EXE_MAP.get(app_name.lower(), f"{app_name.lower()}.exe")
            try:
                result = subprocess.run(
                    f"taskkill /F /IM {exe}",
                    shell=True, capture_output=True, text=True
                )
                if result.returncode == 0:
                    speak(_pick(_CLOSE_REPLIES, app_name.capitalize()))
                else:
                    speak(f"No encontré {app_name.capitalize()} abierta.")
            except Exception as exc:
                print(f"[Interceptor] ❌ taskkill: {exc}")
                speak(f"No pude cerrar {app_name.capitalize()}.")
            return True

    # ══════════════════════════════════════════════════════════════════════
    # 3. ¿QUÉ HORA ES?
    # ══════════════════════════════════════════════════════════════════════
    if _TIME_PATTERN.search(text):
        now  = datetime.now()
        hora = now.strftime("%I:%M %p").lstrip("0")   # ej: "3:45 PM"
        # Convertir a formato hablado
        h   = now.hour % 12 or 12
        m_  = now.minute
        pm  = "de la tarde" if now.hour >= 12 else "de la mañana"
        if m_ == 0:
            hablado = f"Son las {h} en punto {pm}."
        elif m_ == 1:
            hablado = f"Es la {h} y un minuto {pm}."
        else:
            hablado = f"Son las {h} y {m_} minutos {pm}."
        print(f"[Interceptor] 🕐 Hora: {hablado}")
        speak(hablado)
        return True

    # ══════════════════════════════════════════════════════════════════════
    # 4. ¿QUÉ DÍA / FECHA ES?
    # ══════════════════════════════════════════════════════════════════════
    if _DATE_PATTERN.search(text):
        DIAS   = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        MESES  = ["enero","febrero","marzo","abril","mayo","junio",
                  "julio","agosto","septiembre","octubre","noviembre","diciembre"]
        now    = datetime.now()
        dia    = DIAS[now.weekday()]
        fecha  = f"{now.day} de {MESES[now.month - 1]} de {now.year}"
        hablado = f"Hoy es {dia}, {fecha}."
        print(f"[Interceptor] 📅 Fecha: {hablado}")
        speak(hablado)
        return True

    # ══════════════════════════════════════════════════════════════════════
    # 5. VOLUMEN
    # ══════════════════════════════════════════════════════════════════════
    if _MUTE_PATTERN.search(text):
        _press_key(_VK_VOLUME_MUTE)
        speak("¡Listo! Silencié el volumen.")
        return True

    if _VOL_UP_PATTERN.search(text):
        _adjust_volume(steps=5)
        speak("¡Subí el volumen!")
        return True

    if _VOL_DOWN_PATTERN.search(text):
        _adjust_volume(steps=-5)
        speak("¡Bajé el volumen!")
        return True

    # ══════════════════════════════════════════════════════════════════════
    # Aquí puedes añadir más interceptores en el futuro:
    #   _WEATHER_PATTERN → openweathermap API
    #   _JOKE_PATTERN    → lista de chistes locales
    #   _SONG_PATTERN    → controlar Spotify vía subprocess
    # ══════════════════════════════════════════════════════════════════════

    return False   # no interceptado → pasar al LLM
