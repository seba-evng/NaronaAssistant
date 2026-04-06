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

import google.generativeai as genai
from google.generativeai import types as genai_types

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

genai.configure(api_key=_cfg["gemini_api_key"])

with open(_PROMPT_PATH, encoding="utf-8") as _f:
    _SYSTEM_PROMPT = _f.read().strip()

# ---------------------------------------------------------------------------
# TOOL_DECLARATIONS – sin IMU
# ---------------------------------------------------------------------------
TOOL_DECLARATIONS = [
    genai_types.Tool(
        function_declarations=[
            genai_types.FunctionDeclaration(
                name="robot_control",
                description=(
                    "Controla los motores del robot. "
                    "Úsalo para mover el robot hacia adelante, atrás, girar o parar."
                ),
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "action": genai_types.Schema(
                            type=genai_types.Type.STRING,
                            description="Acción: forward | backward | left | right | stop",
                        ),
                        "speed": genai_types.Schema(
                            type=genai_types.Type.NUMBER,
                            description="Velocidad entre 0.0 y 1.0 (default 0.5)",
                        ),
                        "duration": genai_types.Schema(
                            type=genai_types.Type.NUMBER,
                            description="Duración en segundos (default 1.0)",
                        ),
                    },
                    required=["action"],
                ),
            ),
            genai_types.FunctionDeclaration(
                name="sensor_read",
                description=(
                    "Lee sensores del robot. "
                    "Sensores disponibles: distance (HC-SR04), temperature (MLX90614)."
                ),
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "sensor": genai_types.Schema(
                            type=genai_types.Type.STRING,
                            description="Sensor: distance | temperature | all",
                        ),
                    },
                    required=["sensor"],
                ),
            ),
            genai_types.FunctionDeclaration(
                name="camera_remote",
                description=(
                    "Captura una imagen desde la cámara de la Pi Zero y la analiza "
                    "con visión artificial."
                ),
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "text": genai_types.Schema(
                            type=genai_types.Type.STRING,
                            description="Pregunta o descripción para el análisis visual",
                        ),
                        "save": genai_types.Schema(
                            type=genai_types.Type.BOOLEAN,
                            description="Guardar imagen en disco (default false)",
                        ),
                        "timeout": genai_types.Schema(
                            type=genai_types.Type.INTEGER,
                            description="Segundos de espera para la cámara (default 5)",
                        ),
                    },
                    required=["text"],
                ),
            ),
            genai_types.FunctionDeclaration(
                name="agent_task",
                description=(
                    "Delega un objetivo complejo a un sub-agente que lo planifica "
                    "y ejecuta paso a paso."
                ),
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "goal": genai_types.Schema(
                            type=genai_types.Type.STRING,
                            description="Objetivo de alto nivel para el sub-agente",
                        ),
                        "priority": genai_types.Schema(
                            type=genai_types.Type.STRING,
                            description="Prioridad: low | normal | high (default normal)",
                        ),
                    },
                    required=["goal"],
                ),
            ),
        ]
    )
]


# ---------------------------------------------------------------------------
# Clase NaronaAgent
# ---------------------------------------------------------------------------

class NaronaAgent:
    """Orquestador principal del robot NARONA."""

    def __init__(self):
        self._model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=_SYSTEM_PROMPT,
            tools=TOOL_DECLARATIONS,
        )
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
            if history_context:
                chat_system = _SYSTEM_PROMPT + f"\n\n{history_context}"
                chat_model = genai.GenerativeModel(
                    model_name="gemini-2.5-flash",
                    system_instruction=chat_system,
                    tools=TOOL_DECLARATIONS,
                )
                self._chat = chat_model.start_chat()
            else:
                self._chat = self._model.start_chat()

        response = self._chat.send_message(user_text)

        # Ciclo de tool calls
        while response.candidates:
            candidate = response.candidates[0]
            part = candidate.content.parts[0] if candidate.content.parts else None

            if part is None:
                break

            # Tool call
            if hasattr(part, "function_call") and part.function_call.name:
                fc = part.function_call
                tool_result = self._execute_tool(fc)
                # Enviar resultado de vuelta
                response = self._chat.send_message(
                    genai_types.Part.from_function_response(
                        name=fc.name,
                        response={"result": tool_result},
                    )
                )
            else:
                # Respuesta de texto final
                text = candidate.content.parts[0].text if candidate.content.parts else ""
                if text.strip():
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
