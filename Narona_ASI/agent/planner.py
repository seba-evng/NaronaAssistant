"""
agent/planner.py – Planificador para NARONA.
Genera un plan de pasos usando el LLM y la lista de herramientas disponibles.
"""

import json
import os
import re

import google.generativeai as genai

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _cfg = json.load(_f)

genai.configure(api_key=_cfg["gemini_api_key"])

# ---------------------------------------------------------------------------
# Prompt del planificador
# ---------------------------------------------------------------------------
PLANNER_PROMPT = """Eres el módulo de planificación de NARONA, un robot para niños.
Tu tarea es descomponer el objetivo del usuario en pasos simples usando estas herramientas:

HERRAMIENTAS DISPONIBLES:
1. robot_control
   - action (str, requerido): "forward" | "backward" | "left" | "right" | "stop"
   - speed (float, opcional, default 0.5): 0.0 – 1.0
   - duration (float, opcional, default 1.0): segundos

2. sensor_read
   - sensor (str, requerido): "distance" | "temperature" | "all"

3. camera_remote
   - text (str, requerido): pregunta o descripción de lo que se quiere analizar
   - save (bool, opcional, default false): guardar imagen en disco
   - timeout (int, opcional, default 5): segundos de espera

4. code_helper
   - action (str, requerido): "write" | "review" | "debug" | "explain"
   - description (str, requerido): descripción de la tarea
   - language (str, opcional, default "python")
   - file_path (str, opcional): ruta del archivo

5. agent_task
   - goal (str, requerido): objetivo de alto nivel para el sub-agente
   - priority (str, opcional, default "normal"): "low" | "normal" | "high"

REGLAS:
- Devuelve SOLO un JSON válido con la clave "steps" (lista de pasos).
- Cada paso: {"tool": "<nombre>", "parameters": {<parámetros>}, "description": "<qué hace>"}
- Si el objetivo es simple (texto), devuelve steps vacío y usa "direct_response".
- Nunca incluyas IMU ni sensores inexistentes.

FORMATO DE RESPUESTA:
{
  "steps": [
    {"tool": "sensor_read", "parameters": {"sensor": "distance"}, "description": "verificar obstáculos"},
    {"tool": "robot_control", "parameters": {"action": "forward", "duration": 2.0}, "description": "avanzar"}
  ],
  "direct_response": null
}
"""


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def create_plan(goal: str, context: str = "") -> dict:
    """Genera un plan de pasos para alcanzar *goal*.

    Args:
        goal: objetivo del usuario.
        context: contexto adicional (memoria, historial, etc.).

    Returns:
        dict con claves "steps" y "direct_response".
    """
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=PLANNER_PROMPT,
    )
    user_prompt = f"Objetivo: {goal}"
    if context:
        user_prompt += f"\nContexto: {context}"

    try:
        response = model.generate_content(user_prompt)
        raw = response.text.strip()
        # Extraer JSON de posible markdown
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as exc:
        print(f"[planner] Error generando plan: {exc}")

    return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    """Plan de respaldo cuando el LLM falla."""
    return {
        "steps": [],
        "direct_response": f"Lo siento, no pude planificar cómo hacer: {goal}",
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    """Re-planifica tras un fallo en un paso.

    Args:
        goal: objetivo original.
        completed_steps: pasos ya completados.
        failed_step: paso que falló.
        error: mensaje de error.

    Returns:
        Nuevo plan dict.
    """
    context = (
        f"Pasos completados: {json.dumps(completed_steps, ensure_ascii=False)}\n"
        f"Paso fallido: {json.dumps(failed_step, ensure_ascii=False)}\n"
        f"Error: {error}\n"
        f"Por favor genera un plan alternativo para completar el objetivo."
    )
    return create_plan(goal, context)
