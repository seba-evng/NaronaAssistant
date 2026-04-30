"""
actions/robot_control.py - Control del robot por GPIO o ESP32 por serial.
Acciones: forward, backward, left, right, stop.
"""

import json
import os
import threading
import time

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
except Exception:
    _cfg = {}

_SERIAL_PORT = str(_cfg.get("esp32_serial_port", "COM3")).strip()
_SERIAL_BAUDRATE = int(_cfg.get("esp32_baudrate", 115200))
_GREETING_COMMAND = str(_cfg.get("esp32_greeting_command", "saludo")).strip() or "saludo"

# ---------------------------------------------------------------------------
# Guard GPIO
# ---------------------------------------------------------------------------
_GPIO_AVAILABLE = False
_left_motor = None
_right_motor = None

try:
    from gpiozero import Motor  # type: ignore

    _pins = _cfg.get("motor_pins", {})
    _left_motor = Motor(forward=_pins["left_forward"], backward=_pins["left_backward"])
    _right_motor = Motor(forward=_pins["right_forward"], backward=_pins["right_backward"])
    _GPIO_AVAILABLE = True
except Exception as exc:
    print(f"[robot_control] GPIO no disponible (modo simulacion): {exc}")

# ---------------------------------------------------------------------------
# Guard serial ESP32
# ---------------------------------------------------------------------------
_SERIAL_AVAILABLE = False
_serial_module = None
_esp32 = None
_serial_lock = threading.Lock()

try:
    import serial as _serial_module  # type: ignore

    _SERIAL_AVAILABLE = True
except Exception as exc:
    print(f"[robot_control] pyserial no disponible: {exc}")


def _ensure_serial_connection() -> bool:
    """Abre la conexion serial al ESP32 si hace falta."""
    global _esp32

    if not _SERIAL_AVAILABLE or not _SERIAL_PORT:
        return False

    with _serial_lock:
        if _esp32 is not None and getattr(_esp32, "is_open", False):
            return True

        try:
            _esp32 = _serial_module.Serial(_SERIAL_PORT, _SERIAL_BAUDRATE, timeout=1)
            time.sleep(2.0)
            print(f"[robot_control] ESP32 serial conectado en {_SERIAL_PORT}.")
            return True
        except Exception as exc:
            print(f"[robot_control] No se pudo abrir {_SERIAL_PORT}: {exc}")
            _esp32 = None
            return False


def _send_serial_command(command: str) -> str:
    """Envia un comando simple al ESP32."""
    if not command.strip():
        return "Comando vacio."

    if not _ensure_serial_connection():
        return f"[simulacion] serial -> {command}"

    try:
        payload = (command.strip() + "\n").encode("utf-8")
        with _serial_lock:
            _esp32.write(payload)
            _esp32.flush()
        return f"Comando serial enviado: {command}"
    except Exception as exc:
        return f"Error enviando comando serial: {exc}"


def robot_greet() -> str:
    """Mueve el saludo inicial en el ESP32 si esta configurado."""
    return _send_serial_command(_GREETING_COMMAND)


def robot_control(parameters: dict, response=None, player=None) -> str:
    """Controla los motores del robot."""
    action = str(parameters.get("action", "stop")).lower()
    speed = float(parameters.get("speed", 0.5))
    duration = float(parameters.get("duration", 1.0))

    speed = max(0.0, min(1.0, speed))
    duration = max(0.0, duration)

    if _ensure_serial_connection():
        try:
            result = _send_serial_command(action)
            if action != "stop":
                time.sleep(duration)
                _send_serial_command("stop")
            return f"{result} ({duration}s)."
        except Exception as exc:
            return f"Error en robot_control serial: {exc}"

    if not _GPIO_AVAILABLE:
        return f"[simulacion] robot_control: action={action}, speed={speed}, duration={duration}s"

    try:
        _apply_action(action, speed)
        if action != "stop":
            time.sleep(duration)
            _apply_action("stop", 0.0)
        return f"Accion '{action}' completada ({duration}s a velocidad {speed})."
    except Exception as exc:
        return f"Error en robot_control: {exc}"


def _apply_action(action: str, speed: float) -> None:
    if action == "forward":
        _left_motor.forward(speed)
        _right_motor.forward(speed)
    elif action == "backward":
        _left_motor.backward(speed)
        _right_motor.backward(speed)
    elif action == "left":
        _left_motor.backward(speed)
        _right_motor.forward(speed)
    elif action == "right":
        _left_motor.forward(speed)
        _right_motor.backward(speed)
    elif action == "stop":
        _left_motor.stop()
        _right_motor.stop()
    else:
        raise ValueError(f"Accion desconocida: {action}")
