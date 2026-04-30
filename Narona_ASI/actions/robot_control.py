"""
actions/robot_control.py – Control de motores L298N en Raspberry Pi 5.

Modo actual: movimiento directo sin lectura de sensores.
(Los sensores HC-SR04 se habilitarán en una fase posterior.)

PINOUT L298N (desde config/api_keys.json → "motor_pins"):
  Motor A izquierdo  IN1=17, IN2=27, ENA=18 (PWM)
  Motor B derecho    IN3=22, IN4=23, ENB=19 (PWM)

Backend GPIO: usa gpiozero con LGPIOFactory (Pi 5 compatible).
No requiere configurar la variable de entorno GPIOZERO_PIN_FACTORY.
"""

import json
import os
import threading
import time

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
except Exception:
    _cfg = {}

_pins    = _cfg.get("motor_pins", {})
_PIN_IN1 = int(_pins.get("in1", 17))
_PIN_IN2 = int(_pins.get("in2", 27))
_PIN_ENA = int(_pins.get("ena", 18))
_PIN_IN3 = int(_pins.get("in3", 22))
_PIN_IN4 = int(_pins.get("in4", 23))
_PIN_ENB = int(_pins.get("enb", 19))

# ---------------------------------------------------------------------------
# Configurar gpiozero para usar LGPIOFactory (Pi 5) directamente en código
# sin necesidad de la variable de entorno GPIOZERO_PIN_FACTORY
# ---------------------------------------------------------------------------
try:
    import gpiozero as _gz
    from gpiozero.pins.lgpio import LGPIOFactory as _LGPIOFactory  # type: ignore
    _gz.Device.pin_factory = _LGPIOFactory()
except Exception as _pin_factory_exc:
    print(f"[robot_control] Pin factory lgpio no disponible, usando default: {_pin_factory_exc}")

# ---------------------------------------------------------------------------
# Hardware GPIO
# ---------------------------------------------------------------------------
_GPIO_AVAILABLE = False
_in1 = _in2 = _ena = None
_in3 = _in4 = _enb = None

try:
    from gpiozero import OutputDevice, PWMOutputDevice  # type: ignore

    _in1 = OutputDevice(_PIN_IN1, initial_value=False)
    _in2 = OutputDevice(_PIN_IN2, initial_value=False)
    _ena = PWMOutputDevice(_PIN_ENA, initial_value=0)
    _in3 = OutputDevice(_PIN_IN3, initial_value=False)
    _in4 = OutputDevice(_PIN_IN4, initial_value=False)
    _enb = PWMOutputDevice(_PIN_ENB, initial_value=0)

    _GPIO_AVAILABLE = True
    print(
        f"[robot_control] ✅ L298N listo — "
        f"MotorA(IN1={_PIN_IN1}, IN2={_PIN_IN2}, ENA={_PIN_ENA}) | "
        f"MotorB(IN3={_PIN_IN3}, IN4={_PIN_IN4}, ENB={_PIN_ENB})"
    )
except Exception as exc:
    print(f"[robot_control] GPIO no disponible (modo simulación): {exc}")

# Señal global para interrumpir movimiento en curso ("para")
_stop_movement = threading.Event()


# ---------------------------------------------------------------------------
# Primitivas de motor
# ---------------------------------------------------------------------------

def _motor_a(forward: bool, speed: float) -> None:
    if forward:
        _in1.on();  _in2.off()
    else:
        _in1.off(); _in2.on()
    _ena.value = speed


def _motor_b(forward: bool, speed: float) -> None:
    if forward:
        _in3.on();  _in4.off()
    else:
        _in3.off(); _in4.on()
    _enb.value = speed


def _stop_all() -> None:
    _in1.off(); _in2.off(); _ena.value = 0
    _in3.off(); _in4.off(); _enb.value = 0


def _apply_action(action: str, speed: float) -> None:
    if action == "forward":
        _motor_a(True,  speed); _motor_b(True,  speed)
    elif action == "backward":
        _motor_a(False, speed); _motor_b(False, speed)
    elif action == "left":
        _motor_a(False, speed); _motor_b(True,  speed)
    elif action == "right":
        _motor_a(True,  speed); _motor_b(False, speed)
    elif action == "stop":
        _stop_all()
    else:
        raise ValueError(f"Acción desconocida: '{action}'")


# ---------------------------------------------------------------------------
# Movimiento simple (sin sensores)
# ---------------------------------------------------------------------------

def _move(action: str, speed: float, duration: float) -> str:
    """Ejecuta el movimiento durante *duration* segundos respetando la señal de parada."""
    _stop_movement.clear()
    _apply_action(action, speed)

    elapsed = 0.0
    while elapsed < duration:
        if _stop_movement.is_set():
            _stop_all()
            return "¡Paré! Me detuve como me pediste. 🛑"
        time.sleep(0.1)
        elapsed += 0.1

    _stop_all()
    dir_es = {
        "forward":  "adelante",
        "backward": "hacia atrás",
        "left":     "a la izquierda",
        "right":    "a la derecha",
    }.get(action, action)
    return f"¡Listo! Me moví {dir_es} durante {elapsed:.0f} segundos. ✅"


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def robot_control(parameters: dict, response=None, player=None) -> str:
    """Controla los motores del robot NARONA.

    Parámetros:
        action   (str)   – forward | backward | left | right | stop
        speed    (float) – 0.0–1.0  (default 0.5)
        duration (float) – segundos (default 3.0)
    """
    action   = str(parameters.get("action",   "stop")).lower().strip()
    speed    = float(parameters.get("speed",   0.5))
    duration = float(parameters.get("duration", 3.0))

    speed    = max(0.0, min(1.0, speed))
    duration = max(0.0, duration)

    if action == "stop":
        _stop_movement.set()
        if _GPIO_AVAILABLE:
            _stop_all()
        return "¡Me detuve! 🛑"

    if not _GPIO_AVAILABLE:
        dir_es = {
            "forward":  "adelante",
            "backward": "hacia atrás",
            "left":     "a la izquierda",
            "right":    "a la derecha",
        }.get(action, action)
        return (
            f"[simulación] Movería el robot {dir_es}, "
            f"velocidad {int(speed * 100)}%, durante {duration:.0f}s."
        )

    try:
        return _move(action, speed, duration)
    except Exception as exc:
        _stop_all()
        return f"Error en robot_control: {exc}"
