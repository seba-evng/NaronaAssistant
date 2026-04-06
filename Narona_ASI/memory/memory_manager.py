"""
memory/memory_manager.py – Gestión de memoria a largo plazo de NARONA.
Basado en el patrón de FatihMakes/Mark-XXX.
Guarda en memory/memory.json.
"""

import json
import os
import threading
from typing import Any

# ---------------------------------------------------------------------------
# Ruta del archivo de memoria
# ---------------------------------------------------------------------------
_MEMORY_DIR  = os.path.dirname(__file__)
_MEMORY_FILE = os.path.join(_MEMORY_DIR, "memory.json")
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def load_memory() -> dict:
    """Carga la memoria desde disco.

    Returns:
        Diccionario con los datos de memoria.
    """
    with _lock:
        if not os.path.exists(_MEMORY_FILE):
            return {}
        try:
            with open(_MEMORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def update_memory(data: dict) -> None:
    """Actualiza la memoria fusionando *data* con la existente.

    Args:
        data: dict con las claves/valores a actualizar.
    """
    with _lock:
        current = {}
        if os.path.exists(_MEMORY_FILE):
            try:
                with open(_MEMORY_FILE, encoding="utf-8") as f:
                    current = json.load(f)
            except Exception:
                current = {}

        current.update(data)

        os.makedirs(_MEMORY_DIR, exist_ok=True)
        with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)


def format_memory_for_prompt(memory: dict) -> str:
    """Formatea la memoria como texto para incluir en el prompt del LLM.

    Args:
        memory: diccionario de memoria.

    Returns:
        Cadena formateada con las entradas de memoria.
    """
    if not memory:
        return ""

    lines = ["[Memoria de NARONA]"]
    for key, value in memory.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)
