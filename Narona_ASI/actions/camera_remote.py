"""
actions/camera_remote.py – Petición HTTP a la Pi Zero para capturar imagen.
Llama al servidor Flask /capture y luego analiza con vision_client.
"""

import json
import os
import time
from typing import Optional

import requests

from vision.vision_client import analyze_image

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    _PI_ZERO_IP   = _cfg.get("pi_zero_ip", "192.168.1.101")
    _PI_ZERO_PORT = int(_cfg.get("pi_zero_port", 5001))
except Exception:
    _PI_ZERO_IP   = "192.168.1.101"
    _PI_ZERO_PORT = 5001

_CAPTURE_URL = f"http://{_PI_ZERO_IP}:{_PI_ZERO_PORT}/capture"


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def camera_remote(parameters: dict, response=None, player=None) -> str:
    """Captura una imagen de la Pi Zero y la analiza con visión.

    Args:
        parameters: dict con:
            - text (str, requerido): pregunta o descripción para el análisis.
            - save (bool, opcional, default False): guardar imagen en disco.
            - timeout (int, opcional, default 5): segundos de espera HTTP.
        response: no utilizado.
        player: no utilizado.

    Returns:
        Descripción del análisis de la imagen.
    """
    question = str(parameters.get("text", "¿Qué ves en la imagen?"))
    save     = bool(parameters.get("save", False))
    timeout  = int(parameters.get("timeout", 5))

    image_bytes = fetch_camera_image(timeout)
    if image_bytes is None:
        return "No pude obtener imagen de la cámara."

    if save:
        _save_image(image_bytes)

    try:
        result = analyze_image(image_bytes, question)
        return result
    except Exception as exc:
        return f"Error analizando imagen: {exc}"


def fetch_camera_image(timeout: int = 5) -> Optional[bytes]:
    """Captura una imagen JPEG desde el servidor de la Pi Zero.

    Returns:
        Bytes JPEG o None si falla.
    """
    try:
        resp = requests.get(_CAPTURE_URL, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        print(f"[camera_remote] Error obteniendo imagen: {exc}")
        return None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _save_image(image_bytes: bytes):
    save_dir = os.path.join(os.path.dirname(__file__), "..", "captures")
    os.makedirs(save_dir, exist_ok=True)
    filename = os.path.join(save_dir, f"capture_{int(time.time())}.jpg")
    try:
        with open(filename, "wb") as f:
            f.write(image_bytes)
        print(f"[camera_remote] Imagen guardada: {filename}")
    except Exception as exc:
        print(f"[camera_remote] Error guardando imagen: {exc}")
