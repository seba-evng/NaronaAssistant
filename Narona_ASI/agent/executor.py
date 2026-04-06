"""
agent/executor.py – Ejecuta herramientas según su nombre.
Mapeo: nombre_tool → función Python en actions/*.
"""

import json
import os
from typing import Callable, Optional

from actions.robot_control import robot_control
from actions.sensor_read import sensor_read
from actions.camera_remote import camera_remote
from actions.code_helper import code_helper
from actions.navigation import navigation
from agent.planner import create_plan, replan

# ---------------------------------------------------------------------------
# Función de bajo nivel
# ---------------------------------------------------------------------------

def _call_tool(tool: str, parameters: dict, speak: Optional[Callable] = None) -> str:
    """Llama a la función correspondiente a *tool* con *parameters*.

    Args:
        tool: nombre de la herramienta.
        parameters: parámetros de la herramienta.
        speak: función TTS opcional para retroalimentación durante ejecución.

    Returns:
        Resultado como string.
    """
    # Respuesta y player son opcionales en el patrón Mark-XXX;
    # aquí los pasamos como None para compatibilidad.
    response = None
    player = None

    dispatch = {
        "robot_control": lambda: robot_control(parameters, response, player),
        "sensor_read":   lambda: sensor_read(parameters, response, player),
        "camera_remote": lambda: camera_remote(parameters, response, player),
        "code_helper":   lambda: code_helper(parameters, response, player),
        "navigation":    lambda: navigation(parameters, response, player, speak),
    }

    handler = dispatch.get(tool)
    if handler is None:
        return f"[executor] Herramienta desconocida: {tool}"

    try:
        return handler()
    except Exception as exc:
        return f"[executor] Error ejecutando {tool}: {exc}"


# ---------------------------------------------------------------------------
# Clase AgentExecutor
# ---------------------------------------------------------------------------

class AgentExecutor:
    """Ejecuta un objetivo completo usando planificación + herramientas."""

    def __init__(self):
        self._memory_context: str = ""

    def execute(
        self,
        goal: str,
        speak: Optional[Callable] = None,
        cancel_flag=None,
    ) -> str:
        """Ejecuta *goal* paso a paso y devuelve un resumen.

        Args:
            goal: objetivo del usuario.
            speak: función TTS opcional.
            cancel_flag: threading.Event opcional; si se activa, cancela.

        Returns:
            Texto de resumen con los resultados.
        """
        plan = create_plan(goal, self._memory_context)

        if plan.get("direct_response"):
            return plan["direct_response"]

        steps = plan.get("steps", [])
        if not steps:
            return "No sé cómo hacer eso todavía."

        results = []
        completed = []

        for step in steps:
            if cancel_flag and cancel_flag.is_set():
                results.append("Tarea cancelada.")
                break

            tool = step.get("tool", "")
            params = step.get("parameters", {})
            desc = step.get("description", tool)

            if speak:
                speak(f"Voy a {desc}.")

            result = _call_tool(tool, params, speak)
            results.append(f"{desc}: {result}")
            completed.append(step)

            # Si hay error, intentar replanificar una vez
            if result.startswith("[executor] Error"):
                new_plan = replan(goal, completed, step, result)
                remaining = new_plan.get("steps", [])
                steps = remaining  # continúa con los nuevos pasos

        return self._summarize(goal, results)

    def _summarize(self, goal: str, results: list) -> str:
        """Genera un resumen breve de los resultados."""
        if not results:
            return "No hubo resultados."
        summary = " | ".join(results)
        return f"Hice: {summary}"
