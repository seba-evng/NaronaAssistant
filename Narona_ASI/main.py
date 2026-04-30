"""
main.py - Orquestador principal de NARONA.
Arquitectura basada en FatihMakes/Mark-XXX.
"""

import json
import os
import queue
import re
import threading
import time
import traceback

from google import genai
from google.genai import types

from agent.task_queue import Task, get_queue
from memory.memory_manager import (
    format_memory_for_prompt,
    get_child_profile,
    get_missing_child_profile_fields,
    load_memory,
    update_child_profile,
    update_child_profile_meta,
    update_memory,
)
from ui.audio_input import listen_loop, listen_once
from ui.audio_output import speak
from ui.command_interceptor import try_intercept


_BASE_DIR = os.path.dirname(__file__)
_CONFIG_PATH = os.path.join(_BASE_DIR, "config", "api_keys.json")
_PROMPT_PATH = os.path.join(_BASE_DIR, "core", "prompt.txt")

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _cfg = json.load(_f)

with open(_PROMPT_PATH, encoding="utf-8") as _f:
    _SYSTEM_PROMPT = _f.read().strip()


TOOL_DECLARATIONS = [
    {
        "name": "robot_control",
        "description": (
            "Controla los motores del robot NARONA. "
            "Usalo para mover el robot: adelante, atras, girar o parar. "
            "SIEMPRE llama esta herramienta, nunca simules el movimiento."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "forward | backward | left | right | stop"},
                "speed": {"type": "NUMBER", "description": "Velocidad 0.0-1.0 (default 0.5)"},
                "duration": {"type": "NUMBER", "description": "Duracion en segundos (default 1.0)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "sensor_read",
        "description": (
            "Lee sensores fisicos del robot. "
            "Usalo para medir la distancia a obstaculos o la temperatura del entorno."
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
            "Captura una imagen desde la camara del robot y la analiza. "
            "Usala cuando necesites ver el entorno. "
            "NUNCA tienes vision sin llamar esta herramienta."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING", "description": "Pregunta o descripcion para el analisis visual"},
                "save": {"type": "BOOLEAN", "description": "Guardar imagen en disco (default false)"},
                "timeout": {"type": "INTEGER", "description": "Segundos de espera para la camara (default 5)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "open_app",
        "description": (
            "Abre una aplicacion, programa o juego en la computadora. "
            "Usala cuando el nino pida abrir cualquier app. "
            "SIEMPRE llama esta herramienta, nunca digas que abriste algo sin llamarla."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Nombre de la aplicacion a abrir, por ejemplo: WhatsApp, Chrome, Spotify, Minecraft",
                },
                "platform": {
                    "type": "STRING",
                    "description": "Sistema operativo: windows (default) | linux | macos",
                },
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "agent_task",
        "description": (
            "Delega un objetivo complejo de multiples pasos a un sub-agente. "
            "Usalo para tareas como 'avanza hasta detectar un obstaculo'. "
            "NO lo uses para acciones simples de un solo paso."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal": {"type": "STRING", "description": "Objetivo completo para el sub-agente"},
                "priority": {"type": "STRING", "description": "low | normal | high (default normal)"},
            },
            "required": ["goal"],
        },
    },
]


class NaronaAgent:
    """Orquestador principal del robot NARONA."""

    def __init__(self):
        self._client = genai.Client(api_key=_cfg["gemini_api_key"])
        self._model_name = "gemini-2.5-flash"
        self._chat = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

    def _execute_tool(self, fc) -> str:
        """Despacha una FunctionCall al modulo Python correspondiente."""
        name = fc.name
        params = dict(fc.args)

        if name == "robot_control":
            from actions.robot_control import robot_control

            return robot_control(params, None, None)

        if name == "sensor_read":
            from actions.sensor_read import sensor_read

            return sensor_read(params, None, None)

        if name == "camera_remote":
            from actions.camera_remote import camera_remote

            return camera_remote(params, None, None)

        if name == "open_app":
            from actions.open_app import open_app

            return open_app(params, None, None)

        if name == "agent_task":
            goal = str(params.get("goal", ""))
            priority = str(params.get("priority", "normal"))
            task = Task.from_priority_name(goal=goal, priority_name=priority, speak=speak)
            task_id = get_queue().enqueue(task)
            deadline = time.time() + 60
            while time.time() < deadline:
                result = get_queue().get_result(task_id)
                if result is not None:
                    return result
                time.sleep(0.5)
            return "La tarea esta en progreso pero tardara mas de lo esperado."

        return f"Herramienta desconocida: {name}"

    def _build_system_prompt(self) -> str:
        """Construye el system prompt con memoria actualizada."""
        memory = load_memory()
        history_context = format_memory_for_prompt(memory)
        if history_context:
            return history_context + "\n\n" + _SYSTEM_PROMPT
        return _SYSTEM_PROMPT

    def _reset_chat(self) -> None:
        """Fuerza a recrear el chat con memoria fresca."""
        self._chat = None

    def _clean_text(self, value) -> str:
        """Normaliza una respuesta de voz para procesarla mejor."""
        text = str(value or "").strip()
        text = text.replace("?", " ").replace("!", " ").replace(".", " ").replace(",", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _remove_leading_fillers(self, value: str) -> str:
        """Elimina muletillas comunes al inicio de una frase."""
        return re.sub(
            r"^(?:eh+|emm+|mmm+|este+|pues|hola|oye|a ver)\s+",
            "",
            value.strip(),
            flags=re.IGNORECASE,
        )

    def _normalize_name(self, value) -> str:
        """Extrae solo un nombre limpio desde texto libre."""
        text = self._remove_leading_fillers(self._clean_text(value))
        match = re.search(
            r"\b(?:yo\s+me\s+llamo|me\s+llamo|mi\s+nombre\s+es|me\s+dicen|yo\s+soy|soy)\s+(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            text = match.group(1).strip()

        stopwords = {
            "mi",
            "nombre",
            "es",
            "llamo",
            "me",
            "dicen",
            "soy",
            "yo",
            "actualiza",
            "cambia",
            "modifica",
            "corrige",
            "por",
            "favor",
        }

        tokens = []
        for token in text.split():
            clean_token = re.sub(r"[^A-Za-zÁÉÍÓÚáéíóúÑñÜü-]", "", token)
            if not clean_token:
                continue
            if clean_token.lower() in stopwords:
                continue
            tokens.append(clean_token)

        if not tokens or len(tokens) > 3:
            return ""

        return " ".join(token.capitalize() for token in tokens)

    def _normalize_age(self, value) -> str:
        """Extrae una edad valida desde texto libre."""
        text = self._clean_text(value).lower()
        digit_match = re.search(r"\d{1,2}", text)
        if digit_match:
            age = int(digit_match.group())
            if 3 <= age <= 17:
                return str(age)
            return ""

        number_words = {
            "tres": 3,
            "cuatro": 4,
            "cinco": 5,
            "seis": 6,
            "siete": 7,
            "ocho": 8,
            "nueve": 9,
            "diez": 10,
            "once": 11,
            "doce": 12,
            "trece": 13,
            "catorce": 14,
            "quince": 15,
            "dieciseis": 16,
            "dieciséis": 16,
            "diecisiete": 17,
        }
        for word, age in number_words.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                return str(age)
        return ""

    def _normalize_likes(self, value) -> list[str]:
        """Extrae una lista de gustos desde una respuesta libre."""
        if isinstance(value, list):
            raw_items = value
        else:
            text = self._clean_text(value)
            lowered = text.lower()

            prefixes = [
                "me gusta ",
                "me gustan ",
                "mis cosas favoritas son ",
                "mis favoritos son ",
                "me encanta ",
                "me encantan ",
            ]
            for prefix in prefixes:
                if lowered.startswith(prefix):
                    text = text[len(prefix):].strip()
                    break

            text = re.sub(r"\s+y\s+", ",", text, flags=re.IGNORECASE)
            raw_items = re.split(r"[;,/]|,", text)

        likes = []
        seen = set()
        for item in raw_items:
            cleaned = item.strip(" .")
            cleaned = re.sub(r"^(el|la|los|las|un|una)\s+", "", cleaned, flags=re.IGNORECASE)
            if len(cleaned) < 2:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            likes.append(cleaned)

        return likes[:5]

    def _apply_profile_update_from_text(self, user_text: str) -> bool:
        """Detecta cambios explicitos del perfil y los guarda antes del LLM."""
        text = self._remove_leading_fillers(self._clean_text(user_text))
        lowered = text.lower()

        if not re.search(r"\b(actualiza|cambia|modifica|corrige)\b", lowered):
            return False

        updates = {}

        name_match = re.search(
            r"\b(?:actualiza|cambia|modifica|corrige)\s+mi\s+nombre\s+(?:a|por)\s+(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if name_match:
            name = self._normalize_name(name_match.group(1))
            if name:
                updates["name"] = name

        age_match = re.search(
            r"\b(?:actualiza|cambia|modifica|corrige)\s+mi\s+edad\s+(?:a|por)\s+(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if age_match:
            age = self._normalize_age(age_match.group(1))
            if age:
                updates["age"] = age

        likes_match = re.search(
            r"\b(?:actualiza|cambia|modifica|corrige)\s+(?:mis\s+gustos|lo\s+que\s+me\s+gusta)\s+(?:a|por)\s+(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if likes_match:
            likes = self._normalize_likes(likes_match.group(1))
            if likes:
                updates["likes"] = likes

        if not updates:
            return False

        update_child_profile(updates)
        if "likes" in updates:
            update_child_profile_meta({"likes_prompted": True})
        self._reset_chat()

        confirmations = []
        if "name" in updates:
            confirmations.append(f"tu nombre ahora es {updates['name']}")
        if "age" in updates:
            confirmations.append(f"tu edad ahora es {updates['age']}")
        if "likes" in updates:
            confirmations.append("ya guarde tus gustos nuevos")

        message = "Listo, " + " y ".join(confirmations) + "."
        speak(message)
        update_memory({"last_response": message})
        return True

    def _sanitize_child_profile(self) -> dict:
        """Limpia el perfil guardado y elimina datos invalidos."""
        memory = load_memory()
        profile = get_child_profile(memory)
        sanitized_profile = {}

        name = self._normalize_name(profile.get("name", ""))
        age = self._normalize_age(profile.get("age", ""))
        likes = self._normalize_likes(profile.get("likes", ""))

        if name:
            sanitized_profile["name"] = name
        if age:
            sanitized_profile["age"] = age
        if likes:
            sanitized_profile["likes"] = likes

        if sanitized_profile != profile:
            update_memory({"child_profile": sanitized_profile})
            self._reset_chat()

        return sanitized_profile

    def _process_text(self, user_text: str) -> None:
        try:
            if self._chat is None:
                self._chat = self._client.chats.create(
                    model=self._model_name,
                    config=types.GenerateContentConfig(
                        system_instruction=self._build_system_prompt(),
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
                    continue

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

    def _collect_profile_value(self, prompt: str, timeout: int = 8, phrase_limit: int = 8) -> str:
        """Pregunta un dato del perfil y escucha una respuesta breve."""
        for attempt in range(2):
            speak(prompt)
            time.sleep(1.0)
            answer = listen_once(timeout=timeout, phrase_limit=phrase_limit, notify=True).strip()
            if answer:
                print(f"[NARONA] Perfil captado: {answer!r}")
                return answer
            if attempt == 0:
                speak("No te escuche bien. Dime otra vez, por favor.")
                time.sleep(0.8)
        return ""

    def _collect_name(self) -> str:
        """Pregunta el nombre hasta obtener uno limpio."""
        for attempt in range(3):
            answer = self._collect_profile_value("Como te llamas?")
            name = self._normalize_name(answer)
            if name:
                return name
            if attempt < 2:
                speak("Dime solo tu nombre, por favor.")
                time.sleep(0.8)
        return ""

    def _collect_age(self) -> str:
        """Pregunta la edad hasta obtener un numero valido."""
        for attempt in range(3):
            answer = self._collect_profile_value("Cuantos anos tienes?")
            age = self._normalize_age(answer)
            if age:
                return age
            if attempt < 2:
                speak("Dime solo tu edad con un numero corto, por favor.")
                time.sleep(0.8)
        return ""

    def _collect_likes(self) -> list[str]:
        """Pregunta gustos una sola vez y guarda solo si hay al menos tres."""
        answer = self._collect_profile_value("Dime tres cosas que te gusten mucho.")
        update_child_profile_meta({"likes_prompted": True})
        likes = self._normalize_likes(answer)
        if len(likes) >= 3:
            return likes
        return []

    def _run_profile_onboarding(self) -> None:
        """Pregunta datos del nino solo si faltan en memoria."""
        self._sanitize_child_profile()
        memory = load_memory()
        missing_fields = get_missing_child_profile_fields(memory)
        if not missing_fields:
            return

        profile = get_child_profile(memory)
        speak("Quiero conocerte un poquito.")
        time.sleep(0.5)

        if "name" in missing_fields:
            name = self._collect_name()
            if name:
                profile["name"] = name
                update_child_profile({"name": name})

        if "age" in missing_fields:
            age = self._collect_age()
            if age:
                profile["age"] = age
                update_child_profile({"age": age})

        if "likes" in missing_fields:
            likes = self._collect_likes()
            if likes:
                profile["likes"] = likes
                update_child_profile({"likes": likes})

        if profile:
            self._reset_chat()
            child_name = str(profile.get("name", "")).strip()
            if child_name:
                speak(f"Gracias, {child_name}.")
            else:
                speak("Gracias.")

    def _receive_audio(self) -> None:
        while not self._stop_event.is_set():
            try:
                user_text = self._audio_queue.get(timeout=1)
                print(f"[NARONA] User said: {user_text!r}")

                if try_intercept(user_text, speak):
                    continue

                if self._apply_profile_update_from_text(user_text):
                    continue

                self._process_text(user_text)
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"[NARONA] Error in _receive_audio: {exc}")
                traceback.print_exc()
                time.sleep(1)

    def run(self) -> None:
        """Inicia el agente y lo mantiene activo con reconexion automatica."""
        from actions.robot_control import robot_greet

        profile = self._sanitize_child_profile()
        child_name = str(profile.get("name", "")).strip()
        greeting_motion = robot_greet()
        print(f"[NARONA] Greeting motion: {greeting_motion}")

        if child_name:
            speak(f"Hola, {child_name}. Soy NARONA, tu robot amigo.")
        else:
            speak("Hola. Soy NARONA, tu robot amigo.")

        self._run_profile_onboarding()
        speak("Dime en que te puedo ayudar.")

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
                traceback.print_exc()
                time.sleep(2)
                self._chat = None

        speak("Hasta luego. Cuidate mucho.")


def main():
    agent = NaronaAgent()
    agent.run()


if __name__ == "__main__":
    main()
