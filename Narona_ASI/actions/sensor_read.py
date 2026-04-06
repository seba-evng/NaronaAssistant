"""
actions/sensor_read.py – Lectura de sensores de NARONA.
Sensores disponibles: distance (HC-SR04), temperature (MLX90614).
NO incluye IMU/MPU-6050.
"""

import json
import os
from typing import Optional

# ---------------------------------------------------------------------------
# Guards de hardware
# ---------------------------------------------------------------------------
_DISTANCE_AVAILABLE = False
_TEMP_AVAILABLE = False
_distance_sensor = None

try:
    from gpiozero import DistanceSensor  # type: ignore

    _CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)

    _pins = _cfg.get("ultrasonic_pins", {})
    _distance_sensor = DistanceSensor(
        echo=_pins.get("echo", 6),
        trigger=_pins.get("trigger", 5),
    )
    _DISTANCE_AVAILABLE = True
except Exception as _e:
    print(f"[sensor_read] DistanceSensor no disponible: {_e}")

try:
    import smbus2  # type: ignore
    _TEMP_AVAILABLE = True
except Exception as _e:
    print(f"[sensor_read] smbus2 no disponible (modo simulación): {_e}")

# Dirección I2C del MLX90614
_MLX90614_ADDR = 0x5A
_MLX90614_TOBJ1 = 0x07


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def sensor_read(parameters: dict, response=None, player=None) -> str:
    """Lee uno o ambos sensores.

    Args:
        parameters: dict con:
            - sensor (str, requerido): "distance" | "temperature" | "all"
        response: no utilizado.
        player: no utilizado.

    Returns:
        Cadena con la lectura del sensor.
    """
    sensor = str(parameters.get("sensor", "distance")).lower()

    if sensor == "distance":
        return _read_distance()
    elif sensor == "temperature":
        return _read_temperature()
    elif sensor == "all":
        dist = _read_distance()
        temp = _read_temperature()
        return f"{dist} | {temp}"
    else:
        return f"Sensor desconocido: '{sensor}'. Usa 'distance', 'temperature' o 'all'."


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _read_distance() -> str:
    if not _DISTANCE_AVAILABLE:
        return "[simulación] distancia: 100.0 cm"
    try:
        distance_m = _distance_sensor.distance
        distance_cm = round(distance_m * 100, 1)
        return f"distancia: {distance_cm} cm"
    except Exception as exc:
        return f"Error leyendo distancia: {exc}"


def _read_temperature() -> str:
    if not _TEMP_AVAILABLE:
        return "[simulación] temperatura objeto: 36.5 °C"
    try:
        bus = smbus2.SMBus(1)
        raw = bus.read_word_data(_MLX90614_ADDR, _MLX90614_TOBJ1)
        temp_k = raw * 0.02
        temp_c = round(temp_k - 273.15, 2)
        bus.close()
        return f"temperatura objeto: {temp_c} °C"
    except Exception as exc:
        return f"Error leyendo temperatura: {exc}"
