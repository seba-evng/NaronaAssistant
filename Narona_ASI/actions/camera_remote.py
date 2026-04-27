"""
actions/camera_remote.py - Peticion HTTP a la Pi Zero para capturar imagen.
Si el servidor no responde, intenta usar la camara local del dispositivo.
"""

import json
import io
import os
import time
from typing import Callable, Optional

import requests
from PIL import Image, ImageFilter, ImageStat

from vision.vision_client import analyze_image

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "api_keys.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    _PI_ZERO_IP = _cfg.get("pi_zero_ip", "192.168.1.101")
    _PI_ZERO_PORT = int(_cfg.get("pi_zero_port", 5001))
    _LOCAL_CAMERA_INDEX = int(_cfg.get("local_camera_index", 0))
except Exception:
    _PI_ZERO_IP = "192.168.1.101"
    _PI_ZERO_PORT = 5001
    _LOCAL_CAMERA_INDEX = 0

_CAPTURE_URL = f"http://{_PI_ZERO_IP}:{_PI_ZERO_PORT}/capture"


# ---------------------------------------------------------------------------
# Funcion publica
# ---------------------------------------------------------------------------
def camera_remote(parameters: dict, response=None, player=None) -> str:
    """Captura una imagen y la analiza con vision."""
    question = str(parameters.get("text", "Que ves en la imagen?"))
    save = bool(parameters.get("save", False))
    timeout = int(parameters.get("timeout", 5))

    image_bytes, quality_issue = _capture_best_image(fetch_camera_image, timeout)
    if image_bytes is None:
        image_bytes, local_issue = _capture_best_image(fetch_local_camera_image, timeout)
        quality_issue = local_issue or quality_issue

    if image_bytes is None:
        if quality_issue:
            return (
                "Pude intentar la camara, pero la imagen se ve "
                f"{quality_issue}. Intenta con mas luz o sin mover la camara."
            )
        return (
            "No pude obtener imagen ni del servidor de la camara "
            "ni de la camara local del dispositivo."
        )

    if save:
        _save_image(image_bytes)

    try:
        return analyze_image(image_bytes, question)
    except Exception as exc:
        return f"Error analizando imagen: {exc}"


def fetch_camera_image(timeout: int = 5) -> Optional[bytes]:
    """Captura una imagen JPEG desde el servidor de la Pi Zero."""
    try:
        resp = requests.get(_CAPTURE_URL, timeout=timeout)
        resp.raise_for_status()
        if _is_placeholder_image(resp.content):
            print("[camera_remote] El servidor devolvio una imagen simulada.")
            return None
        return resp.content
    except Exception as exc:
        print(f"[camera_remote] Error obteniendo imagen del servidor: {exc}")
        return None


def _capture_best_image(
    fetcher: Callable[[int], Optional[bytes]],
    timeout: int,
    attempts: int = 3,
) -> tuple[Optional[bytes], Optional[str]]:
    """Intenta varias capturas y filtra imagenes oscuras o borrosas."""
    last_issue = None

    for attempt in range(attempts):
        image_bytes = fetcher(timeout)
        if image_bytes is None:
            continue

        quality_issue = _check_image_quality(image_bytes)
        if quality_issue is None:
            return image_bytes, None

        last_issue = quality_issue
        print(
            f"[camera_remote] Imagen descartada por calidad ({quality_issue}). "
            f"Reintento {attempt + 1}/{attempts}."
        )
        time.sleep(0.2)

    return None, last_issue


def fetch_local_camera_image(timeout: int = 5) -> Optional[bytes]:
    """Captura una imagen JPEG desde la camara local del dispositivo."""
    try:
        import cv2  # type: ignore
    except Exception as exc:
        print(f"[camera_remote] OpenCV no disponible para camara local: {exc}")
        return None

    capture = None
    backends = [None]
    if os.name == "nt":
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]

    try:
        for backend in backends:
            capture = _open_local_camera(cv2, _LOCAL_CAMERA_INDEX, backend)
            if capture is None or not capture.isOpened():
                if capture is not None:
                    capture.release()
                capture = None
                continue

            deadline = time.time() + max(timeout, 1)
            frame = None

            while time.time() < deadline:
                ok, current_frame = capture.read()
                if ok and current_frame is not None:
                    frame = current_frame
                    break
                time.sleep(0.1)

            if frame is None:
                capture.release()
                capture = None
                continue

            ok, encoded = cv2.imencode(".jpg", frame)
            if not ok:
                print("[camera_remote] No se pudo codificar la imagen local a JPEG.")
                capture.release()
                return None

            capture.release()
            print("[camera_remote] Usando fallback de camara local.")
            return encoded.tobytes()

        print("[camera_remote] No se pudo abrir ninguna camara local.")
        return None
    except Exception as exc:
        print(f"[camera_remote] Error usando camara local: {exc}")
        return None
    finally:
        if capture is not None:
            capture.release()


def _open_local_camera(cv2_module, camera_index: int, backend) -> Optional[object]:
    """Abre la camara local usando un backend opcional."""
    try:
        if backend is None:
            return cv2_module.VideoCapture(camera_index)
        return cv2_module.VideoCapture(camera_index, backend)
    except Exception as exc:
        print(f"[camera_remote] Error abriendo camara local: {exc}")
        return None


def _is_placeholder_image(image_bytes: bytes) -> bool:
    """Detecta la imagen 1x1 usada por el servidor en modo simulacion."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return image.size == (1, 1)
    except Exception:
        return False


def _check_image_quality(image_bytes: bytes) -> Optional[str]:
    """Detecta si la imagen esta demasiado oscura o borrosa."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            grayscale = image.convert("L")
            brightness = ImageStat.Stat(grayscale).mean[0]

            edges = grayscale.filter(ImageFilter.FIND_EDGES)
            sharpness = ImageStat.Stat(edges).var[0]

            if brightness < 28:
                return "muy oscura"
            if sharpness < 45:
                return "borrosa"
            return None
    except Exception as exc:
        print(f"[camera_remote] No se pudo evaluar la calidad de la imagen: {exc}")
        return None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _save_image(image_bytes: bytes) -> None:
    save_dir = os.path.join(os.path.dirname(__file__), "..", "captures")
    os.makedirs(save_dir, exist_ok=True)
    filename = os.path.join(save_dir, f"capture_{int(time.time())}.jpg")
    try:
        with open(filename, "wb") as f:
            f.write(image_bytes)
        print(f"[camera_remote] Imagen guardada: {filename}")
    except Exception as exc:
        print(f"[camera_remote] Error guardando imagen: {exc}")
