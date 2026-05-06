"""
ui/wake_word.py – Detección de wake word "narona" con fuzzy matching.

API pública:
    detect_wake_word(text)      → (bool, str)  detecta si el texto activa el wake word
    strip_wake_word(text)       → str          devuelve el texto sin la palabra de activación
    play_notification_sound()   → None         reproduce SonidoNoti.mp3 (llamado por audio_input)

No depende de paquetes externos: usa difflib (stdlib).
Umbral configurable: SIMILARITY_THRESHOLD (0-100).
"""

import difflib
import os
import re

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "Assets")


# ──────────────────────────────────────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────────────────────────────────────

WAKE_TARGET          = "narona"
SIMILARITY_THRESHOLD = 80        # porcentaje mínimo para activar (0-100)

# Lista de variaciones conocidas (match directo, sin coste de cómputo)
WAKE_VARIATIONS: frozenset[str] = frozenset({
    # Exactas / muy cercanas
    "narona", "naronaa", "narana", "norona", "nerona", "nirona", "nurona",
    # Consonante inicial diferente
    "marona", "maronna", "darona", "tarona", "garona", "barona",
    # Palabras similares en fonética o longitud
    "madona", "maradona", "naruto", "nara", "corona", "neurona",
    # Abreviaciones frecuentes
    "naro", "naron", "nanona", "narola", "narota",
    # Variaciones con tilde o doble letra
    "naróna", "naronita", "naroona",
    # Doble consonante — errores comunes de STT con acento español
    "narrona", "maronna", "narrona",
    # Errores de STT con separación
    "narona,", "narona.",
})

# Palabras tan cortas que son ruido puro (se ignoran aunque hagan match)
_NOISE_WORDS: frozenset[str] = frozenset({
    "na", "no", "ne", "ni", "a", "e", "o",
})


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _fuzzy_score(a: str, b: str) -> float:
    """Similaridad entre dos strings, rango 0-100."""
    return difflib.SequenceMatcher(None, a, b).ratio() * 100


def _tokenize(text: str) -> list[str]:
    """Extrae palabras en minúsculas eliminando puntuación."""
    return re.findall(r"[a-záéíóúñü]+", text.lower())


def _word_is_wake(word: str) -> tuple[bool, float]:
    """
    Evalúa si una palabra es la wake word.

    Returns:
        (match: bool, score: float)  score en rango 0-100
    """
    if len(word) < 3 or word in _NOISE_WORDS:
        return False, 0.0

    # Coincidencia directa con variaciones (rápido, sin regex)
    if word in WAKE_VARIATIONS:
        score = _fuzzy_score(word, WAKE_TARGET)
        # Las variaciones garantizan activación incluso si score < threshold
        return True, max(score, SIMILARITY_THRESHOLD)

    # Fuzzy match contra la palabra objetivo
    score = _fuzzy_score(word, WAKE_TARGET)
    return score >= SIMILARITY_THRESHOLD, score


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def detect_wake_word(text: str) -> tuple[bool, str]:
    """
    Comprueba si el texto contiene el wake word.

    Estrategia:
    1. Tokeniza el texto (palabras individuales en minúsculas).
    2. Para cada token: comprueba lista de variaciones O fuzzy score >= umbral.
    3. También comprueba bigramas (ej. "la rona" → "larona").

    Returns:
        (detected: bool, matched_word: str)
    """
    tokens = _tokenize(text)
    if not tokens:
        return False, ""

    # Comprobar tokens individuales
    for word in tokens:
        matched, score = _word_is_wake(word)
        if matched:
            print(f"[wake_word] '{word}' → {score:.0f}% ≥ {SIMILARITY_THRESHOLD}% → ACTIVADO")
            return True, word

    # Comprobar bigramas (por si STT separa "na rona" en dos tokens)
    for i in range(len(tokens) - 1):
        bigram = tokens[i] + tokens[i + 1]
        matched, score = _word_is_wake(bigram)
        if matched:
            print(f"[wake_word] bigrama '{bigram}' → {score:.0f}% → ACTIVADO")
            return True, bigram

    return False, ""


def strip_wake_word(text: str) -> str:
    """
    Elimina la palabra de activación del texto y devuelve el resto como comando.

    Ejemplo:
        "narona ve hacia adelante"  →  "ve hacia adelante"
        "oye narona, muévete"       →  "oye muevete"
    """
    tokens = re.findall(r"[a-záéíóúñü]+", text.lower())
    result = []
    skip_next = False

    for i, word in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue

        matched, _ = _word_is_wake(word)
        if matched:
            continue  # descartar la wake word

        # Descartar bigrama: si la siguiente palabra forma la wake word con esta
        if i < len(tokens) - 1:
            bigram = word + tokens[i + 1]
            bmatched, _ = _word_is_wake(bigram)
            if bmatched:
                skip_next = True
                continue

        result.append(word)

    return " ".join(result)


# ──────────────────────────────────────────────────────────────────────────────
# Utilidad de sonido (importada también por audio_input.py)
# ──────────────────────────────────────────────────────────────────────────────

def play_notification_sound() -> None:
    """
    Reproduce Assets/SonidoNoti.mp3 usando pygame.mixer.

    Llamada por:
    - audio_input.py  → antes de abrir el micrófono
    - face.py         → al activar el modo escucha activa
    """
    try:
        import pygame
        sound_path = os.path.join(_ASSETS_DIR, "SonidoNoti.mp3")
        if not os.path.exists(sound_path):
            return
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        snd = pygame.mixer.Sound(sound_path)
        snd.play()
    except Exception as exc:
        print(f"[wake_word] Error reproduciendo SonidoNoti.mp3: {exc}")
