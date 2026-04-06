"""
main.py – Orquestador principal de NARONA.
Arquitectura basada en FatihMakes/Mark-XXX.
"""

import json
import os
import queue
import threading
import time
from typing import Optional

from google import genai
from google.genai import types

from ui.audio_input import listen_loop
from ui.audio_output import speak, speak_async
from memory.memory_manager import load_memory, update_memory, format_memory_for_prompt
from agent.task_queue import get_queue, Task

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
_BASE_DIR    = os.path.dirname(__file__)
_CONFIG_PATH = os.path.join(_BASE_DIR, "config", "api_keys.json")
_PROMPT_PATH = os.path.join(_BASE_DIR, "core", "prompt.txt")

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _cfg = json.load(_f)

with open(_PROMPT_PATH, encoding="utf-8") as _f:
    _SYSTEM_PROMPT = _f.read().strip()

# ---------------------------------------------------------------------------
# TOOL_DECLARATIONS – sin IMU
# ---------------------------------------------------------------------------
TOOL_DECLARATIONS = [
    {
        "name": "robot_control",
        "description": (
            "Controla los motores del robot NARONA. "
            "Úsalo para mover el robot: adelante, atrás, girar o parar. "
            "SIEMPRE llama esta herramienta — nunca simules el movimiento."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "forward | backward | left | right | stop"},
                "speed":    {"type": "NUMBER", "description": "Velocidad 0.0–1.0 (default 0.5)"},
                "duration": {"type": "NUMBER", "description": "Duración en segundos (default 1.0)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "sensor_read",
        "description": (
            "Lee sensores físicos del robot. "
            "Úsalo para medir la distancia a obstáculos o la temperatura del entorno."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "sensor": {"type": "STRING", "description": "distance | temperature | all (default: distance)"},
            },
            "required": ["sensor"],
        },
    },
    {
        "name": "camera_remote",
        "description": (
            "Captura una imagen desde la cámara de la Pi Zero y la analiza. "
            "Úsalo cuando necesites ver el entorno. "
            "NUNCA tienes visión sin llamar esta herramienta."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text":    {"type": "STRING",  "description": "Pregunta o descripción para el análisis visual"},
                "save":    {"type": "BOOLEAN", "description": "Guardar imagen en disco (default false)"},
                "timeout": {"type": "INTEGER", "description": "Segundos de espera para la cámara (default 5)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "agent_task",
        "description": (
            "Delega un objetivo complejo de múltiples pasos a un sub-agente. "
            "Úsalo para tareas como 'avanza hasta detectar un obstáculo'. "
            "NO uses para acciones simples de un solo paso."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Objetivo completo para el sub-agente"},
                "priority": {"type": "STRING", "description": "low | normal | high (default normal)"},
            },
            "required": ["goal"],
        },
    },
]


# ---------------------------------------------------------------------------
# Clase NaronaAgent
# ---------------------------------------------------------------------------

class NaronaAgent:
    """Orquestador principal del robot NARONA."""

    def __init__(self):
        self._client = genai.Client(api_key=_cfg["gemini_api_key"])
        self._model_name = "gemini-2.5-flash"
        self._chat = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Herramientas internas
    # ------------------------------------------------------------------

    def _execute_tool(self, fc) -> str:
        """Despacha una FunctionCall al módulo Python correspondiente."""
        name   = fc.name
        params = dict(fc.args)

        if name == "robot_control":
            from actions.robot_control import robot_control
            return robot_control(params, None, None)

        elif name == "sensor_read":
            from actions.sensor_read import sensor_read
            return sensor_read(params, None, None)

        elif name == "camera_remote":
            from actions.camera_remote import camera_remote
            return camera_remote(params, None, None)

        elif name == "agent_task":
            goal     = str(params.get("goal", ""))
            priority = str(params.get("priority", "normal"))
            task = Task.from_priority_name(goal=goal, priority_name=priority, speak=speak)
            task_id = get_queue().enqueue(task)
            # Esperar resultado (máximo 60s)
            deadline = time.time() + 60
            while time.time() < deadline:
                result = get_queue().get_result(task_id)
                if result is not None:
                    return result
                time.sleep(0.5)
            return "La tarea está en progreso pero tardará más de lo esperado."

        else:
            return f"Herramienta desconocida: {name}"

    # ------------------------------------------------------------------
    # Ciclo de conversación
    # ------------------------------------------------------------------

    def _process_text(self, user_text: str) -> None:
        """Procesa el texto del usuario y genera la respuesta."""
        if self._chat is None:
            memory = load_memory()
            history_context = format_memory_for_prompt(memory)
            system = _SYSTEM_PROMPT
            if history_context:
                system = history_context + "\n\n" + system
            self._chat = self._client.chats.create(
                model=self._model_name,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=[{"function_declarations": TOOL_DECLARATIONS}],
                ),
            )

        response = self._chat.send_message(user_text)

        # Ciclo de tool calls
        while True:
            part = response.candidates[0].content.parts[0] if (
                response.candidates and response.candidates[0].content.parts
            ) else None

            if part is None:
                break

            if hasattr(part, "function_call") and part.function_call and part.function_call.name:
                fc = part.function_call
                tool_result = self._execute_tool(fc)
                response = self._chat.send_message(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": tool_result},
                    )
                )
            else:
                text = part.text if hasattr(part, "text") else ""
                if text and text.strip():
                    speak(text.strip())
                    update_memory({"last_response": text.strip()})
                break

    def _listen_audio(self) -> None:
        """Bucle STT que pone texto en la cola de audio."""
        def callback(text: str):
            self._audio_queue.put(text)

        listen_loop(callback, self._stop_event)

    def _receive_audio(self) -> None:
        """Saca texto de la cola y lo procesa."""
        while not self._stop_event.is_set():
            try:
                user_text = self._audio_queue.get(timeout=1)
                print(f"[NARONA] Usuario dijo: {user_text}")
                self._process_text(user_text)
            except queue.Empty:
                continue
            except Exception as exc:
                print(f"[NARONA] Error procesando mensaje: {exc}")
                time.sleep(1)

    # ------------------------------------------------------------------
    # Bucle principal con reconexión automática
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Inicia el agente y lo mantiene activo con reconexión automática."""
        speak("¡Hola! Soy NARONA. ¿En qué te puedo ayudar hoy?")

        listen_thread = threading.Thread(target=self._listen_audio, daemon=True)
        listen_thread.start()

        while not self._stop_event.is_set():
            try:
                self._receive_audio()
            except KeyboardInterrupt:
                print("\n[NARONA] Deteniendo...")
                self._stop_event.set()
                break
            except Exception as exc:
                print(f"[NARONA] Error en bucle principal, reconectando: {exc}")
                time.sleep(2)
                # Reiniciar chat en caso de error de API
                self._chat = None

        speak("¡Hasta luego! Cuídate mucho.")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main():
    agent = NaronaAgent()
    agent.run()


if __name__ == "__main__":
    main()
