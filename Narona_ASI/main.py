"""
main.py – Orquestador principal de NARONA.
Arquitectura basada en FatihMakes/Mark-XXX.
"""

import json
import os
import queue
import threading
import time
import traceback
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
        try:
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

            for _ in range(5):
                fc = None
                if response.candidates:
                    for candidate in response.candidates:
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if (
                                    hasattr(part, "function_call")
                                    and part.function_call is not None
                                    and getattr(part.function_call, "name", None)
                                ):
                                    fc = part.function_call
                                    break
                        if fc:
                            break

                if fc:
                    print(f"[NARONA] Tool call: {fc.name}")
                    tool_result = self._execute_tool(fc)
                    print(f"[NARONA] {fc.name} result: {str(tool_result)[:80]}")
                    response = self._chat.send_message(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"result": tool_result},
                        )
                    )
                else:
                    text = ""
                    try:
                        text = response.text or ""
                    except Exception:
                        if response.candidates:
                            for candidate in response.candidates:
                                if candidate.content and candidate.content.parts:
                                    for part in candidate.content.parts:
                                        if hasattr(part, "text") and part.text:
                                            text += part.text

                    text = text.strip()
                    if text:
                        print(f"[NARONA] Speaking: {text[:120]}")
                        speak(text)
                        update_memory({"last_response": text})
                    else:
                        print("[NARONA] Warning: empty response from LLM")
                    break

        except Exception as exc:
            print(f"[NARONA] Error in _process_text: {exc}")
            traceback.print_exc()
            self._chat = None

    def _listen_audio(self) -> None:
        """Bucle STT que pone texto en la cola de audio."""
        def callback(text: str):
            self._audio_queue.put(text)

        listen_loop(callback, self._stop_event)

    def _receive_audio(self) -> None:
        while not self._stop_event.is_set():
            try:
                user_text = self._audio_queue.get(timeout=1)
                print(f"[NARONA] User said: {user_text!r}")
                self._process_text(user_text)
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"[NARONA] Error in _receive_audio: {exc}")
                traceback.print_exc()
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
