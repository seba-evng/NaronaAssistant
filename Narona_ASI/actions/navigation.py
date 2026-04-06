"""
actions/navigation.py – Estrategias de navegación para NARONA.
Usa sensor_read(distance) + robot_control. Sin IMU.
"""

import time
from typing import Callable, Optional

from actions.sensor_read import sensor_read
from actions.robot_control import robot_control

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
_OBSTACLE_THRESHOLD_CM = 30.0   # distancia mínima segura en cm
_CHECK_INTERVAL_S      = 0.3    # intervalo entre lecturas de distancia
_DEFAULT_SPEED         = 0.5
_DEFAULT_MAX_DURATION  = 30.0   # segundos máximos de navegación


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def navigation(
    parameters: dict,
    response=None,
    player=None,
    speak: Optional[Callable] = None,
) -> str:
    """Ejecuta una estrategia de navegación.

    Args:
        parameters: dict con:
            - strategy (str, opcional, default "navigate_until_obstacle")
            - speed (float, opcional, default 0.5)
            - max_duration (float, opcional, default 30.0): segundos máximos
            - threshold_cm (float, opcional, default 30.0): distancia de parada
        response: no utilizado.
        player: no utilizado.
        speak: función TTS opcional.

    Returns:
        Mensaje de resultado.
    """
    strategy     = str(parameters.get("strategy", "navigate_until_obstacle"))
    speed        = float(parameters.get("speed", _DEFAULT_SPEED))
    max_duration = float(parameters.get("max_duration", _DEFAULT_MAX_DURATION))
    threshold_cm = float(parameters.get("threshold_cm", _OBSTACLE_THRESHOLD_CM))

    if strategy == "navigate_until_obstacle":
        return _navigate_until_obstacle(speed, max_duration, threshold_cm, speak)
    else:
        return f"Estrategia desconocida: '{strategy}'."


# ---------------------------------------------------------------------------
# Estrategia interna
# ---------------------------------------------------------------------------

def _navigate_until_obstacle(
    speed: float,
    max_duration: float,
    threshold_cm: float,
    speak: Optional[Callable],
) -> str:
    """Avanza hasta detectar un obstáculo o agotar el tiempo máximo."""
    start = time.time()

    while True:
        elapsed = time.time() - start
        if elapsed >= max_duration:
            robot_control({"action": "stop"}, None, None)
            return f"Navegación completada ({elapsed:.1f}s). No detecté obstáculos."

        # Leer distancia
        dist_result = sensor_read({"sensor": "distance"}, None, None)
        dist_cm = _parse_distance(dist_result)

        if dist_cm is not None and dist_cm < threshold_cm:
            robot_control({"action": "stop"}, None, None)
            msg = f"¡Obstáculo detectado a {dist_cm:.1f} cm! Me detuve."
            if speak:
                speak(msg)
            return msg

        # Avanzar un paso corto
        robot_control(
            {"action": "forward", "speed": speed, "duration": _CHECK_INTERVAL_S},
            None, None,
        )

    # No se llega aquí, pero por completitud:
    return "Navegación finalizada."


def _parse_distance(dist_str: str) -> Optional[float]:
    """Extrae el valor numérico en cm de la cadena devuelta por sensor_read."""
    try:
        # Formato esperado: "distancia: 45.3 cm"
        parts = dist_str.split(":")
        if len(parts) >= 2:
            value_part = parts[-1].strip().split()[0]
            return float(value_part)
    except Exception:
        pass
    return None
