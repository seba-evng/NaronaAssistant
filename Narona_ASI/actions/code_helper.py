"""
actions/code_helper.py – Herramienta de ayuda de código para NARONA.
Basado en el patrón de FatihMakes/Mark-XXX.
"""

import json
import os
from typing import Optional

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
    print(f"[code_helper] No se pudo cargar api_keys.json: {_e}")

_SYSTEM_PROMPT = (
    "Eres un asistente experto en programación. "
    "Das respuestas concisas, claras y con ejemplos de código cuando es útil. "
    "Responde siempre en el mismo idioma de la solicitud."
)


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def code_helper(parameters: dict, response=None, player=None) -> str:
    """Herramienta de ayuda de código.

    Args:
        parameters: dict con:
            - action (str, requerido): "write" | "review" | "debug" | "explain"
            - description (str, requerido): descripción de la tarea.
            - language (str, opcional, default "python"): lenguaje de programación.
            - file_path (str, opcional): ruta del archivo a revisar/depurar.
        response: no utilizado.
        player: no utilizado.

    Returns:
        Respuesta del LLM como string.
    """
    action      = str(parameters.get("action", "explain")).lower()
    description = str(parameters.get("description", ""))
    language    = str(parameters.get("language", "python"))
    file_path   = parameters.get("file_path")

    file_content = ""
    if file_path:
        try:
            with open(file_path, encoding="utf-8") as f:
                file_content = f.read()
        except Exception as exc:
            file_content = f"[No se pudo leer el archivo: {exc}]"

    prompt = _build_prompt(action, description, language, file_content)

    try:
        if _client is None:
            return "Error: cliente de código no inicializado (falta api_keys.json)"
        result = _client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=_SYSTEM_PROMPT),
        )
        return result.text.strip()
    except Exception as exc:
        return f"Error en code_helper: {exc}"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_prompt(action: str, description: str, language: str, file_content: str) -> str:
    base = f"Lenguaje: {language}\nTarea: {description}"
    if file_content:
        base += f"\n\nCódigo:\n```{language}\n{file_content}\n```"

    prompts = {
        "write":   f"Escribe código {language} para: {description}",
        "review":  f"Revisa el siguiente código {language} y sugiere mejoras:\n{base}",
        "debug":   f"Depura el siguiente código {language} y explica los errores:\n{base}",
        "explain": f"Explica el siguiente código {language}:\n{base}",
    }
    return prompts.get(action, base)
