"""
vision/vision_client.py – Análisis de imágenes con Google Gemini.
System prompt adaptado para NARONA (robot para niños).
"""

import json
import os

from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

_client: genai.Client | None = None
try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    _client = genai.Client(api_key=_cfg["gemini_api_key"])
except Exception as _e:
    print(f"[vision_client] No se pudo cargar api_keys.json: {_e}")

_VISION_SYSTEM_PROMPT = (
    "Eres NARONA, un robot amigo que ayuda a niños de 8 años. "
    "Cuando describes lo que ves en una imagen, usas frases MUY cortas y simples. "
    "Nunca uses palabras difíciles. "
    "Eres alegre, amable y paciente. "
    "Máximo 2 frases simples por respuesta."
)

_MODEL_NAME = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def analyze_image(image_bytes: bytes, question: str = "¿Qué ves en la imagen?") -> str:
    """Analiza una imagen JPEG y responde la pregunta dada.

    Args:
        image_bytes: bytes de la imagen JPEG.
        question: pregunta a responder sobre la imagen.

    Returns:
        Descripción textual generada por Gemini.
    """
    try:
        if _client is None:
            return "Error: cliente de visión no inicializado (falta api_keys.json)"
        response = _client.models.generate_content(
            model=_MODEL_NAME,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                question,
            ],
            config=types.GenerateContentConfig(system_instruction=_VISION_SYSTEM_PROMPT),
        )
        return response.text.strip()
    except Exception as exc:
        return f"Error analizando imagen: {exc}"
