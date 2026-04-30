"""
memory/memory_manager.py – Gestión de memoria a largo plazo de NARONA.
Basado en el patrón de FatihMakes/Mark-XXX.
Guarda en memory/memory.json.
"""

import json
import os
import threading

# ---------------------------------------------------------------------------
# Ruta del archivo de memoria
# ---------------------------------------------------------------------------
_MEMORY_DIR  = os.path.dirname(__file__)
_MEMORY_FILE = os.path.join(_MEMORY_DIR, "memory.json")
_lock = threading.Lock()
_PROFILE_META_KEY = "child_profile_meta"


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


def update_child_profile(data: dict) -> None:
    """Actualiza el perfil del nino dentro de la memoria."""
    with _lock:
        current = {}
        if os.path.exists(_MEMORY_FILE):
            try:
                with open(_MEMORY_FILE, encoding="utf-8") as f:
                    current = json.load(f)
            except Exception:
                current = {}

        profile = current.get("child_profile", {})
        if not isinstance(profile, dict):
            profile = {}

        profile.update(data)
        current["child_profile"] = profile

        os.makedirs(_MEMORY_DIR, exist_ok=True)
        with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)


def update_child_profile_meta(data: dict) -> None:
    """Actualiza metadata auxiliar del perfil del nino."""
    with _lock:
        current = {}
        if os.path.exists(_MEMORY_FILE):
            try:
                with open(_MEMORY_FILE, encoding="utf-8") as f:
                    current = json.load(f)
            except Exception:
                current = {}

        meta = current.get("child_profile_meta", {})
        if not isinstance(meta, dict):
            meta = {}

        meta.update(data)
        current["child_profile_meta"] = meta

        os.makedirs(_MEMORY_DIR, exist_ok=True)
        with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)


def get_child_profile_meta(memory: dict | None = None) -> dict:
    """Devuelve metadatos del onboarding del nino."""
    if memory is None:
        memory = load_memory()
    meta = memory.get(_PROFILE_META_KEY, {})
    return meta if isinstance(meta, dict) else {}


def update_child_profile_meta(data: dict) -> None:
    """Actualiza metadatos asociados al perfil del nino."""
    with _lock:
        current = {}
        if os.path.exists(_MEMORY_FILE):
            try:
                with open(_MEMORY_FILE, encoding="utf-8") as f:
                    current = json.load(f)
            except Exception:
                current = {}

        meta = current.get(_PROFILE_META_KEY, {})
        if not isinstance(meta, dict):
            meta = {}

        meta.update(data)
        current[_PROFILE_META_KEY] = meta

        os.makedirs(_MEMORY_DIR, exist_ok=True)
        with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)


def get_child_profile(memory: dict | None = None) -> dict:
    """Devuelve el perfil guardado del nino."""
    if memory is None:
        memory = load_memory()
    profile = memory.get("child_profile", {})
    return profile if isinstance(profile, dict) else {}


def get_missing_child_profile_fields(memory: dict | None = None) -> list[str]:
    """Indica que datos del perfil del nino faltan por guardar."""
    profile = get_child_profile(memory)
    meta = get_child_profile_meta(memory)
    required_fields = ["name", "age", "likes"]
    missing_fields = []

    for field in required_fields:
        value = profile.get(field, "")
        if field == "likes":
            if meta.get("likes_prompted"):
                continue
            if isinstance(value, list):
                if len([item for item in value if str(item).strip()]) < 3:
                    missing_fields.append(field)
            elif not str(value).strip():
                missing_fields.append(field)
            continue

        if not str(value).strip():
            missing_fields.append(field)

    return missing_fields


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

    profile = get_child_profile(memory)
    if profile:
        lines.append("- Perfil del nino:")
        if profile.get("name"):
            lines.append(f"  nombre: {profile['name']}")
        if profile.get("age"):
            lines.append(f"  edad: {profile['age']}")
        if profile.get("likes"):
            likes = profile["likes"]
            if isinstance(likes, list):
                lines.append(f"  gustos: {', '.join(str(item) for item in likes)}")
            else:
                lines.append(f"  gustos: {likes}")

    for key, value in memory.items():
        if key in {"child_profile", _PROFILE_META_KEY}:
            continue
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)
