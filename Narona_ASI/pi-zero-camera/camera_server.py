"""
pi-zero-camera/camera_server.py – Servidor Flask para la cámara de la Pi Zero.
Expone GET /capture (devuelve JPEG) y GET /health.
Guard _PICAM_OK para simulación en PC.
"""

import io
import json
import os

from flask import Flask, Response, jsonify

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "camera_config.json")

try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        _cfg = json.load(_f)
    _HOST   = _cfg.get("host", "0.0.0.0")
    _PORT   = int(_cfg.get("port", 5001))
    _WIDTH  = int(_cfg.get("width", 1280))
    _HEIGHT = int(_cfg.get("height", 720))
except Exception:
    _HOST   = "0.0.0.0"
    _PORT   = 5001
    _WIDTH  = 1280
    _HEIGHT = 720

# ---------------------------------------------------------------------------
# Guard picamera2
# ---------------------------------------------------------------------------
_PICAM_OK = False
_picam = None

try:
    from picamera2 import Picamera2  # type: ignore
    _picam = Picamera2()
    _picam.configure(
        _picam.create_still_configuration(
            main={"size": (_WIDTH, _HEIGHT), "format": "RGB888"}
        )
    )
    _picam.start()
    _PICAM_OK = True
except Exception as _e:
    print(f"[camera_server] picamera2 no disponible (modo simulación): {_e}")

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    """Comprobación de salud del servidor."""
    return jsonify({"status": "ok", "picam": _PICAM_OK})


@app.route("/capture", methods=["GET"])
def capture():
    """Captura una imagen y la devuelve como JPEG."""
    if _PICAM_OK and _picam is not None:
        return _capture_real()
    return _capture_simulated()


def _capture_real() -> Response:
    try:
        from PIL import Image  # type: ignore
        import numpy as np

        frame = _picam.capture_array()
        img = Image.fromarray(frame)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return Response(buf.read(), mimetype="image/jpeg")
    except Exception as exc:
        return Response(f"Error capturando imagen: {exc}", status=500)


def _capture_simulated() -> Response:
    """Devuelve una imagen JPEG mínima (1×1 pixel negro) como simulación."""
    from PIL import Image  # type: ignore

    img = Image.new("RGB", (1, 1), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return Response(buf.read(), mimetype="image/jpeg")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"[camera_server] Iniciando en {_HOST}:{_PORT} (picam={_PICAM_OK})")
    app.run(host=_HOST, port=_PORT, debug=False)
