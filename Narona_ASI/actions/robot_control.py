"""
actions/robot_control.py – Control de motores L298N en Raspberry Pi 5.

Modo actual: movimiento directo sin lectura de sensores.
(Los sensores HC-SR04 se habilitarán en una fase posterior.)

PINOUT L298N (desde config/api_keys.json → "motor_pins"):
  Motor A izquierdo  IN1=17, IN2=27
  Motor B derecho    IN3=23, IN4=24

Nota: ENA y ENB se dejan en puente (HIGH fijo) directo en el L298N.
Backend GPIO: usa gpiozero con LGPIOFactory (Pi 5 compatible).
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
_PIN_IN3 = int(_pins.get("in3", 23))
_PIN_IN4 = int(_pins.get("in4", 24))

# Límite de duración por seguridad (segundos)
_MAX_DURATION = 3.0

# ---------------------------------------------------------------------------
# Configurar gpiozero para usar LGPIOFactory (Pi 5)
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
_in1 = _in2 = _in3 = _in4 = None

try:
    from gpiozero import OutputDevice  # type: ignore

    _in1 = OutputDevice(_PIN_IN1, initial_value=False)
    _in2 = OutputDevice(_PIN_IN2, initial_value=False)
    _in3 = OutputDevice(_PIN_IN3, initial_value=False)
    _in4 = OutputDevice(_PIN_IN4, initial_value=False)

    _GPIO_AVAILABLE = True
    print(
        f"[robot_control] ✅ L298N listo — "
        f"MotorA(IN1={_PIN_IN1}, IN2={_PIN_IN2}) | "
        f"MotorB(IN3={_PIN_IN3}, IN4={_PIN_IN4})"
    )
except Exception as exc:
    print(f"[robot_control] GPIO no disponible (modo simulación): {exc}")

# Señal global para interrumpir movimiento en curso
_stop_movement = threading.Event()


# ---------------------------------------------------------------------------
# Primitivas de motor
# ---------------------------------------------------------------------------

def _motor_a(forward: bool) -> None:
    if forward:
        _in1.on();  _in2.off()
    else:
        _in1.off(); _in2.on()

def _motor_b(forward: bool) -> None:
    if forward:
        _in3.on();  _in4.off()
    else:
        _in3.off(); _in4.on()

def _stop_all() -> None:
    _in1.off(); _in2.off()
    _in3.off(); _in4.off()

def _apply_action(action: str) -> None:
    if action == "forward":
        _motor_a(True);  _motor_b(True)
    elif action == "backward":
        _motor_a(False); _motor_b(False)
    elif action == "left":
        _in1.off(); _in2.off()
        _motor_b(True)
    elif action == "right":
        _motor_a(True)
        _in3.off(); _in4.off()
    elif action == "spin_left":
        _motor_a(False); _motor_b(True)
    elif action == "spin_right":
        _motor_a(True);  _motor_b(False)
    elif action == "stop":
        _stop_all()
    else:
        raise ValueError(f"Acción desconocida: '{action}'")


# ---------------------------------------------------------------------------
# Movimiento con límite de tiempo y señal de parada
# ---------------------------------------------------------------------------

_DIR_ES = {
    "forward":    "adelante",
    "backward":   "hacia atrás",
    "left":       "a la izquierda",
    "right":      "a la derecha",
    "spin_left":  "girando en sitio a la izquierda",
    "spin_right": "girando en sitio a la derecha",
}

def _move(action: str, duration: float) -> str:
    duration = min(duration, _MAX_DURATION)
    _stop_movement.clear()
    _apply_action(action)

    elapsed = 0.0
    while elapsed < duration:
        if _stop_movement.is_set():
            _stop_all()
            return f"movimiento_interrumpido: el robot se detuvo antes de completar la acción '{action}'."
        time.sleep(0.1)
        elapsed += 0.1

    _stop_all()
    return f"movimiento_completado: el robot se movió {_DIR_ES.get(action, action)} durante {elapsed:.1f} segundos."


# ---------------------------------------------------------------------------
# Helpers de servo (PCA9685)
# ---------------------------------------------------------------------------

def _mover_suave_servo(s, inicio: float, fin: float, pasos: int = 30, delay: float = 0.01) -> None:
    """Mueve un servo suavemente interpolando entre dos ángulos."""
    step = (fin - inicio) / pasos
    for i in range(pasos + 1):
        s.angle = inicio + step * i
        time.sleep(delay)


def _init_pca():
    """Inicializa y devuelve (pca, servo0, servo1). Lanza excepción si falla."""
    import board
    import busio
    from adafruit_pca9685 import PCA9685
    from adafruit_motor import servo as adafruit_servo

    i2c = busio.I2C(board.SCL, board.SDA)
    pca = PCA9685(i2c)
    pca.frequency = 50
    servo0 = adafruit_servo.Servo(pca.channels[0])
    servo1 = adafruit_servo.Servo(pca.channels[1])
    return pca, servo0, servo1


# ---------------------------------------------------------------------------
# Saludo de inicio (canal 0)
# ---------------------------------------------------------------------------

def startup_greeting() -> None:
    """
    Saludo de inicio: levanta el brazo derecho (canal 0), saluda 3 veces
    con sube-baja y regresa a posición original (0°).
    """
    try:
        pca, servo0, _ = _init_pca()
        print("[robot_control] 👋 Ejecutando saludo de inicio...")

        servo0.angle = 0
        time.sleep(0.5)

        _mover_suave_servo(servo0, 0, 150, pasos=40, delay=0.02)
        time.sleep(0.5)

        for _ in range(3):
            _mover_suave_servo(servo0, 150, 170, pasos=10, delay=0.03)
            time.sleep(0.15)
            _mover_suave_servo(servo0, 170, 150, pasos=10, delay=0.03)
            time.sleep(0.15)

        time.sleep(0.20)
        _mover_suave_servo(servo0, 150, 0, pasos=40, delay=0.02)

        pca.deinit()
        print("[robot_control] ✅ Saludo de inicio completado.")

    except ImportError:
        print("[robot_control] adafruit_motor/PCA9685 no disponible, saludo omitido.")
    except Exception as exc:
        print(f"[robot_control] Error en saludo de inicio: {exc}")


# ---------------------------------------------------------------------------
# Celebración (canales 0 y 1 — ambos brazos)
# ---------------------------------------------------------------------------

def celebrate() -> str:
    """
    Celebración: levanta ambos brazos (canales 0 y 1) simultáneamente,
    los agita 3 veces y los baja. Se ejecuta cuando el niño quiere celebrar.
    """
    try:
        pca, servo0, servo1 = _init_pca()
        print("[robot_control] 🎉 Ejecutando celebración...")

        # Posición inicial
        servo0.angle = 0
        servo1.angle = 0
        time.sleep(0.4)

        # Levantar ambos brazos simultáneamente paso a paso
        pasos_subida = 40
        for i in range(pasos_subida + 1):
            servo0.angle = (150 / pasos_subida) * i
            servo1.angle = (150 / pasos_subida) * i
            time.sleep(0.02)

        time.sleep(0.3)

        # Agitar ambos brazos 3 veces
        for _ in range(3):
            for i in range(11):
                servo0.angle = 150 + (20 / 10) * i
                servo1.angle = 150 + (20 / 10) * i
                time.sleep(0.03)
            time.sleep(0.1)
            for i in range(11):
                servo0.angle = 170 - (20 / 10) * i
                servo1.angle = 170 - (20 / 10) * i
                time.sleep(0.03)
            time.sleep(0.1)

        time.sleep(0.3)

        # Bajar ambos brazos simultáneamente
        pasos_bajada = 40
        for i in range(pasos_bajada + 1):
            servo0.angle = 150 - (150 / pasos_bajada) * i
            servo1.angle = 150 - (150 / pasos_bajada) * i
            time.sleep(0.02)

        pca.deinit()
        print("[robot_control] ✅ Celebración completada.")
        return "celebracion_completada: NARONA levantó ambos brazos y celebró."

    except ImportError:
        return "celebracion_omitida: adafruit_motor/PCA9685 no disponible."
    except Exception as exc:
        return f"error_celebracion: {exc}"


# ---------------------------------------------------------------------------
# Función pública (llamada desde main.py → _execute_tool)
# ---------------------------------------------------------------------------

def robot_control(parameters: dict, response=None, player=None) -> str:
    """Controla los motores y servos del robot NARONA.

    Parámetros:
        action   (str)   – forward | backward | left | right |
                           spin_left | spin_right | stop | celebrate
        duration (float) – segundos, máximo 3.0 (default 2.0, no aplica a celebrate)

    Devuelve un string de estado para Gemini, no para el niño.
    """
    action   = str(parameters.get("action", "stop")).lower().strip()
    duration = float(parameters.get("duration", 2.0))
    duration = max(0.0, duration)

    # Celebración
    if action == "celebrate":
        return celebrate()

    # Parada inmediata
    if action == "stop":
        _stop_movement.set()
        if _GPIO_AVAILABLE:
            _stop_all()
        return "movimiento_detenido: el robot se detuvo correctamente."

    # Modo simulación (sin GPIO): mismo formato que movimiento real → Gemini responde natural
    if not _GPIO_AVAILABLE:
        action_es = _DIR_ES.get(action, action)
        dur = min(duration, _MAX_DURATION)
        return f"movimiento_completado: el robot se movió {action_es} durante {dur:.1f} segundos."


    # Movimiento real
    try:
        return _move(action, duration)
    except Exception as exc:
        _stop_all()
        return f"error_movimiento: {exc}"