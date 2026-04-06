"""
vision/vision_client.py – Análisis de imágenes con Google Gemini.
System prompt adaptado para NARONA (robot para niños).
"""

import json
import os

import google.generativeai as genai

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    genai.configure(api_key=_cfg["gemini_api_key"])
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
        model = genai.GenerativeModel(
            model_name=_MODEL_NAME,
            system_instruction=_VISION_SYSTEM_PROMPT,
        )
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}
        response = model.generate_content([question, image_part])
        return response.text.strip()
    except Exception as exc:
        return f"Error analizando imagen: {exc}"
