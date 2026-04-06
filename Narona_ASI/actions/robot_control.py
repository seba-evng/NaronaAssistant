"""
actions/robot_control.py – Control de motores con gpiozero.
Acciones: forward, backward, left, right, stop.
Guard _GPIO_AVAILABLE para simulación en PC.
"""

import time
import json
import os
from typing import Optional

# ---------------------------------------------------------------------------
# Guard GPIO
# ---------------------------------------------------------------------------
_GPIO_AVAILABLE = False
_left_motor = None
_right_motor = None

try:
    from gpiozero import Motor  # type: ignore
    import json as _json

    _CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = _json.load(_f)

    _pins = _cfg.get("motor_pins", {})
    _left_motor  = Motor(forward=_pins["left_forward"],  backward=_pins["left_backward"])
    _right_motor = Motor(forward=_pins["right_forward"], backward=_pins["right_backward"])
    _GPIO_AVAILABLE = True
except Exception as _e:
    print(f"[robot_control] GPIO no disponible (modo simulación): {_e}")


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def robot_control(parameters: dict, response=None, player=None) -> str:
    """Controla los motores del robot.

    Args:
        parameters: dict con:
            - action (str, requerido): "forward"|"backward"|"left"|"right"|"stop"
            - speed (float, opcional, default 0.5): 0.0 – 1.0
            - duration (float, opcional, default 1.0): segundos de movimiento
        response: no utilizado (compatibilidad Mark-XXX).
        player: no utilizado (compatibilidad Mark-XXX).

    Returns:
        Mensaje descriptivo del resultado.
    """
    action   = str(parameters.get("action", "stop")).lower()
    speed    = float(parameters.get("speed", 0.5))
    duration = float(parameters.get("duration", 1.0))

    speed = max(0.0, min(1.0, speed))
    duration = max(0.0, duration)

    if not _GPIO_AVAILABLE:
        return f"[simulación] robot_control: action={action}, speed={speed}, duration={duration}s"

    try:
        _apply_action(action, speed)
        if action != "stop":
            time.sleep(duration)
            _apply_action("stop", 0.0)
        return f"Acción '{action}' completada ({duration}s a velocidad {speed})."
    except Exception as exc:
        return f"Error en robot_control: {exc}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_action(action: str, speed: float):
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
        raise ValueError(f"Acción desconocida: {action}")
