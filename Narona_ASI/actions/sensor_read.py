"""
actions/sensor_read.py – Lectura de sensores de NARONA (Raspberry Pi 5).

Sensores disponibles:
  HC-SR04 (ultrasónicos, 3 unidades)
    Frontal   → Trig GPIO 5  / Echo GPIO 6
    Izquierdo → Trig GPIO 12 / Echo GPIO 13
    Derecho   → Trig GPIO 16 / Echo GPIO 20

  MLX90614 (temperatura infrarroja, I2C)
    SDA → GPIO 2
    SCL → GPIO 3
    Dirección I2C: 0x5A

Configuración de pines en config/api_keys.json → "ultrasonic_pins".
"""

import json
import os
from typing import Optional

# ---------------------------------------------------------------------------
# Configuración de pines
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
except Exception:
    _cfg = {}

_pins = _cfg.get("ultrasonic_pins", {})

# Pines por sensor
_FRONT = {
    "trigger": int(_pins.get("front_trigger", 5)),
    "echo":    int(_pins.get("front_echo",    6)),
}
_LEFT = {
    "trigger": int(_pins.get("left_trigger",  12)),
    "echo":    int(_pins.get("left_echo",     13)),
}
_RIGHT = {
    "trigger": int(_pins.get("right_trigger", 16)),
    "echo":    int(_pins.get("right_echo",    20)),
}

# ---------------------------------------------------------------------------
# Inicialización HC-SR04
# ---------------------------------------------------------------------------
_DISTANCE_AVAILABLE = False
_sensor_front = None
_sensor_left  = None
_sensor_right = None

try:
    from gpiozero import DistanceSensor  # type: ignore

    _sensor_front = DistanceSensor(
        echo=_FRONT["echo"], trigger=_FRONT["trigger"], max_distance=4.0
    )
    _sensor_left = DistanceSensor(
        echo=_LEFT["echo"],  trigger=_LEFT["trigger"],  max_distance=4.0
    )
    _sensor_right = DistanceSensor(
        echo=_RIGHT["echo"], trigger=_RIGHT["trigger"], max_distance=4.0
    )
    _DISTANCE_AVAILABLE = True
    print(
        f"[sensor_read] ✅ 3× HC-SR04 listos – "
        f"Frontal(T={_FRONT['trigger']}/E={_FRONT['echo']}) | "
        f"Izquierdo(T={_LEFT['trigger']}/E={_LEFT['echo']}) | "
        f"Derecho(T={_RIGHT['trigger']}/E={_RIGHT['echo']})"
    )

except Exception as exc:
    print(f"[sensor_read] DistanceSensor no disponible (modo simulación): {exc}")

# ---------------------------------------------------------------------------
# Inicialización MLX90614 (I2C)
# ---------------------------------------------------------------------------
_TEMP_AVAILABLE = False

try:
    import smbus2  # type: ignore
    _TEMP_AVAILABLE = True
    print("[sensor_read] ✅ smbus2 disponible – MLX90614 listo")
except Exception as exc:
    print(f"[sensor_read] smbus2 no disponible (modo simulación): {exc}")

_MLX90614_ADDR  = 0x5A
_MLX90614_TOBJ1 = 0x07


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def sensor_read(parameters: dict, response=None, player=None) -> str:
    """Lee uno o varios sensores del robot.

    Args:
        parameters:
            sensor (str) – "distance" | "front" | "left" | "right"
                          | "temperature" | "all"
                          (default: "distance")

    Returns:
        Cadena con la(s) lectura(s) del sensor.
    """
    sensor = str(parameters.get("sensor", "distance")).lower().strip()

    if sensor in ("distance", "front"):
        return _read_front()
    elif sensor == "left":
        return _read_left()
    elif sensor == "right":
        return _read_right()
    elif sensor == "temperature":
        return _read_temperature()
    elif sensor == "all":
        parts = [
            _read_front(),
            _read_left(),
            _read_right(),
            _read_temperature(),
        ]
        return " | ".join(parts)
    else:
        return (
            f"Sensor desconocido: '{sensor}'. "
            "Usa 'distance', 'front', 'left', 'right', 'temperature' o 'all'."
        )


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _cm(sensor) -> Optional[float]:
    """Devuelve distancia en cm, o None si falla."""
    try:
        return round(sensor.distance * 100, 1)
    except Exception:
        return None


def _read_front() -> str:
    if not _DISTANCE_AVAILABLE:
        return "[simulación] frontal: 100.0 cm"
    d = _cm(_sensor_front)
    return f"frontal: {d} cm" if d is not None else "Error leyendo sensor frontal"


def _read_left() -> str:
    if not _DISTANCE_AVAILABLE:
        return "[simulación] izquierdo: 100.0 cm"
    d = _cm(_sensor_left)
    return f"izquierdo: {d} cm" if d is not None else "Error leyendo sensor izquierdo"


def _read_right() -> str:
    if not _DISTANCE_AVAILABLE:
        return "[simulación] derecho: 100.0 cm"
    d = _cm(_sensor_right)
    return f"derecho: {d} cm" if d is not None else "Error leyendo sensor derecho"


def _read_temperature() -> str:
    if not _TEMP_AVAILABLE:
        return "[simulación] temperatura objeto: 36.5 °C"
    try:
        bus = smbus2.SMBus(1)
        raw    = bus.read_word_data(_MLX90614_ADDR, _MLX90614_TOBJ1)
        temp_c = round(raw * 0.02 - 273.15, 2)
        bus.close()
        return f"temperatura objeto: {temp_c} °C"
    except Exception as exc:
        return f"Error leyendo MLX90614: {exc}"
