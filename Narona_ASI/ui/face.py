"""
ui/face.py – Cara animada de NARONA (ventana pygame con ojos expresivos).

API pública (thread-safe):
    start()               → abre la ventana en un hilo de fondo
    stop()                → cierra la ventana
    set_emotion(emotion)  → cambia la expresión: normal | feliz | triste | confuso
    notify_message()      → reinicia el contador de inactividad (llama cuando el usuario habla)

El render corre a 60 fps en su propio hilo daemon.
Si pygame no está instalado o falla, el módulo falla silenciosamente
para no interrumpir al resto del sistema.
"""

import math
import os
import random
import threading
import time

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "Assets")

# ──────────────────────────────────────────────────────────────────────────────
# Estado global (acceso protegido por _lock)
# ──────────────────────────────────────────────────────────────────────────────
_lock              = threading.Lock()
_user_emotion: str = "normal"
_last_msg_time: float = time.time()
_running: bool     = False
_thread: threading.Thread | None = None

VALID_EMOTIONS = {"normal", "feliz", "triste", "confuso"}
_IDLE_EMOTION  = "lineas"
_IDLE_TIMEOUT  = 60.0       # segundos sin mensaje → cara de espera
_listening_mode: bool = False   # True durante la escucha activa (wake word)


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def set_emotion(emotion: str) -> str:
    """Cambia la expresión de los ojos. Devuelve confirmación como string."""
    global _user_emotion, _last_msg_time
    emotion = emotion.lower().strip()
    if emotion not in VALID_EMOTIONS:
        return f"Emoción '{emotion}' no reconocida. Usa: {', '.join(sorted(VALID_EMOTIONS))}"
    with _lock:
        _user_emotion  = emotion
        _last_msg_time = time.time()
    print(f"[face] 😊 Emoción → {emotion}")
    return f"cara:{emotion}"


def notify_message() -> None:
    """Reinicia el contador de inactividad cuando el usuario habla."""
    global _last_msg_time
    with _lock:
        _last_msg_time = time.time()


def show_listening() -> None:
    """
    Activa el modo escucha activa:
    - Muestra Assets/Escucha.jpg en la ventana pygame.
    - Reproduce Assets/SonidoNoti.mp3 (no bloqueante).
    """
    global _listening_mode
    with _lock:
        _listening_mode = True
        _last_msg_time  = time.time()   # evitar que la cara entre en idle
    print("[face] 🎤 Modo escucha activa")
    threading.Thread(target=_play_notification_sound, daemon=True).start()


def hide_listening() -> None:
    """Desactiva el modo escucha activa y vuelve a los ojos animados."""
    global _listening_mode
    with _lock:
        _listening_mode = False
        _last_msg_time  = time.time()
    print("[face] Modo escucha desactivado")


def _play_notification_sound() -> None:
    """Delega la reproducción del sonido al módulo centralizado wake_word."""
    from ui.wake_word import play_notification_sound
    play_notification_sound()


def start() -> None:
    """Inicia la ventana de cara en un hilo daemon."""
    global _running, _thread
    if _running:
        return
    _running = True
    _thread  = threading.Thread(target=_run_loop, daemon=True, name="NaronaFace")
    _thread.start()
    print("[face] Ventana de ojos iniciada.")


def stop() -> None:
    """Señaliza el hilo para que cierre pygame."""
    global _running
    _running = False


# ──────────────────────────────────────────────────────────────────────────────
# Helpers matemáticos (sin dependencias externas)
# ──────────────────────────────────────────────────────────────────────────────

def _clamp(value, lo, hi):
    return max(lo, min(hi, value))

def _lerp(a, b, t):
    return a + (b - a) * t

def _smoothstep(t):
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)

def _mix_color(c1, c2, t):
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
    )

def _interp_state(from_state, to_state, t):
    return {k: _lerp(from_state[k], to_state[k], t) for k in from_state}


# ──────────────────────────────────────────────────────────────────────────────
# Estados de expresión
# ──────────────────────────────────────────────────────────────────────────────

def _eye_state(emotion, happy_hop):
    st = {
        "top_scale": 1.0, "bot_scale": 1.0,
        "y_off": 0.0, "tilt": 0.0,
        "arc": 0.0, "arc_h_mul": 1.0, "arc_thickness": 10.0,
        "line": 0.0, "line_len_mul": 0.9, "line_thickness": 10.0,
    }
    if emotion == "feliz":
        st.update({
            "top_scale": 0.24, "bot_scale": 0.17,
            "y_off": -5.0 - happy_hop, "tilt": 2.0,
            "arc": 1.0,
            "arc_h_mul": 0.84 + 0.05 * (happy_hop / 6.0),
            "arc_thickness": 8.0 + happy_hop * 0.5,
        })
    elif emotion == "triste":
        st.update({"top_scale": 0.55, "bot_scale": 0.35,
                   "y_off": 10.0, "tilt": 24.0, "arc": 0.0})
    elif emotion == "confuso":
        st.update({"top_scale": 0.50, "bot_scale": 0.50,
                   "y_off": 4.0, "tilt": 0.0, "arc": 0.0})
    elif emotion == _IDLE_EMOTION:
        st.update({"top_scale": 0.15, "bot_scale": 0.15,
                   "y_off": 12.0, "tilt": 0.0, "arc": 0.0,
                   "line": 1.0, "line_len_mul": 0.72, "line_thickness": 13.0})
    return st


def _brow_state(emotion, is_left):
    hidden = {
        "visible": 0.0,
        "outer_dx": -74.0 if is_left else 74.0, "outer_dy": -20.0,
        "inner_dx":  24.0 if is_left else -24.0, "inner_dy": -20.0,
        "mid_lift": 0.0, "thickness": 8.0,
    }
    if emotion == "triste":
        return {
            "visible": 1.0,
            "outer_dx": -76.0 if is_left else 76.0, "outer_dy": -6.0,
            "inner_dx":  26.0 if is_left else -26.0, "inner_dy": -44.0,
            "mid_lift": -10.0, "thickness": 8.0,
        }
    return hidden


# ──────────────────────────────────────────────────────────────────────────────
# Dibujo
# ──────────────────────────────────────────────────────────────────────────────

def _draw_eye(surface, center, open_ratio,
              from_em, to_em, blend, is_left,
              happy_hop, idle_breath,
              WHITE, LIGHT_BLUE, eye_radius, pygame):
    x, y  = center
    w     = eye_radius
    h     = int(eye_radius * open_ratio)
    fs    = _eye_state(from_em, happy_hop)
    ts    = _eye_state(to_em,   happy_hop)
    st    = _interp_state(fs, ts, blend)

    top_h  = max(int(h * st["top_scale"]), 4)
    bot_h  = max(int(h * st["bot_scale"]), 4)
    eye_y  = int(y + st["y_off"] + idle_breath)
    cap_v  = _clamp(1.0 - max(st["arc"], st["line"]), 0.0, 1.0)
    cap_c  = _mix_color(LIGHT_BLUE, WHITE, cap_v)

    if cap_v > 0.01:
        rect = pygame.Rect(x - w, eye_y - top_h, w * 2, top_h + bot_h)
        pygame.draw.rect(surface, cap_c, rect, border_radius=50)
        tilt = st["tilt"]
        if abs(tilt) > 0.5:
            inner_y = eye_y - top_h - int(tilt * 0.5)
            outer_y = eye_y - top_h + int(tilt * 0.5)
            if is_left:
                outer_pt = (x - w - 8, outer_y); inner_pt = (x + w + 8, inner_y)
            else:
                inner_pt = (x - w - 8, inner_y); outer_pt = (x + w + 8, outer_y)
            pygame.draw.polygon(surface, LIGHT_BLUE, [
                (x - w - 14, eye_y - top_h - 90),
                (x + w + 14, eye_y - top_h - 90),
                outer_pt, inner_pt,
            ])

    if st["arc"] > 0.01:
        arc_c = _mix_color(LIGHT_BLUE, WHITE, st["arc"])
        arc_h = int(w * st["arc_h_mul"])
        arc_y = eye_y - int(12 + happy_hop * 0.4)
        arc_rect = pygame.Rect(x - w, arc_y, w * 2, arc_h)
        thickness = max(int(st["arc_thickness"]), 2)
        pygame.draw.arc(surface, arc_c, arc_rect, 0, math.pi, thickness)

    if st["line"] > 0.01:
        line_c  = _mix_color(LIGHT_BLUE, WHITE, st["line"])
        half    = int(w * st["line_len_mul"])
        thick   = max(int(st["line_thickness"]), 2)
        line_y  = eye_y + int(idle_breath)
        start   = (x - half, line_y); end = (x + half, line_y)
        pygame.draw.line(surface, line_c, start, end, thick)
        pygame.draw.circle(surface, line_c, start, thick // 2)
        pygame.draw.circle(surface, line_c, end,   thick // 2)


def _draw_brow(surface, center, from_em, to_em, blend, is_left,
               WHITE, LIGHT_BLUE, eye_radius, pygame):
    x, y    = center
    base_y  = y - eye_radius - 2
    fs      = _brow_state(from_em, is_left)
    ts      = _brow_state(to_em,   is_left)
    st      = _interp_state(fs, ts, blend)

    if st["visible"] <= 0.01:
        return
    color   = _mix_color(LIGHT_BLUE, WHITE, st["visible"])
    outer_x = int(x + st["outer_dx"]); outer_y = int(base_y + st["outer_dy"])
    inner_x = int(x + st["inner_dx"]); inner_y = int(base_y + st["inner_dy"])
    mid_x   = (outer_x + inner_x) // 2
    mid_y   = int(min(outer_y, inner_y) + st["mid_lift"])
    thick   = max(int(st["thickness"]), 2)
    pygame.draw.lines(surface, color, False,
                      [(outer_x, outer_y), (mid_x, mid_y), (inner_x, inner_y)], thick)
    pygame.draw.circle(surface, color, (outer_x, outer_y), thick // 2)
    pygame.draw.circle(surface, color, (inner_x, inner_y), thick // 2)


# ──────────────────────────────────────────────────────────────────────────────
# Loop principal (corre en su propio hilo)
# ──────────────────────────────────────────────────────────────────────────────

def _run_loop() -> None:
    global _running

    try:
        import pygame
    except ImportError:
        print("[face] pygame no disponible → cara desactivada.")
        return

    try:
        pygame.init()

        # ── Fullscreen: obtener resolución real de la pantalla ──────────────
        info   = pygame.display.Info()
        SCR_W  = info.current_w
        SCR_H  = info.current_h
        screen = pygame.display.set_mode((SCR_W, SCR_H), pygame.FULLSCREEN)
        pygame.display.set_caption("NARONA")
        pygame.mouse.set_visible(False)          # ocultar cursor en kiosko
        clock  = pygame.time.Clock()

        # ── Posiciones y tamaños responsivos ────────────────────────────────
        # Los ojos se distribuyen en el centro vertical y separan
        # horizontalmente en tercios de la pantalla.
        EYE_R  = int(min(SCR_W, SCR_H) * 0.16)  # radio ~ 16% del lado menor
        EYE_Y  = SCR_H // 2
        L_EYE  = (SCR_W // 3,      EYE_Y)
        R_EYE  = (SCR_W * 2 // 3,  EYE_Y)

        WHITE      = (240, 240, 255)
        LIGHT_BLUE = (180, 220, 240)

        # ── Pre-cargar imagen de escucha escalada a fullscreen ───────────────
        _listen_surf = None
        try:
            img_path = os.path.join(_ASSETS_DIR, "Escucha.jpg")
            if os.path.exists(img_path):
                raw = pygame.image.load(img_path)
                _listen_surf = pygame.transform.scale(raw, (SCR_W, SCR_H))
                print("[face] Escucha.jpg cargada.")
            else:
                print(f"[face] Escucha.jpg no encontrada en {img_path}")
        except Exception as exc:
            print(f"[face] Error cargando Escucha.jpg: {exc}")

        # Transición suave entre emociones
        tr_from  = "normal"
        tr_to    = "normal"
        tr_start = 0.0
        TR_DUR   = 0.34
        tr_active = False

        # Parpadeo
        next_blink     = time.time() + random.uniform(2, 4)
        blinking       = False
        blink_progress = 0.0

        def draw_face(open_ratio, f_em, t_em, blend, now):
            screen.fill(LIGHT_BLUE)

            happy_w    = _lerp(1.0 if f_em == "feliz" else 0.0,
                               1.0 if t_em == "feliz" else 0.0, blend)
            idle_w     = _lerp(1.0 if f_em == _IDLE_EMOTION else 0.0,
                               1.0 if t_em == _IDLE_EMOTION else 0.0, blend)
            happy_hop  = 6.0 * max(0.0, math.sin(now * 16.0)) * happy_w
            idle_breath= 2.0 * math.sin(now * 2.4) * idle_w

            for center, left in ((L_EYE, True), (R_EYE, False)):
                _draw_eye(screen, center, open_ratio, f_em, t_em, blend,
                          left, happy_hop, idle_breath, WHITE, LIGHT_BLUE, EYE_R, pygame)
                _draw_brow(screen, center, f_em, t_em, blend, left,
                           WHITE, LIGHT_BLUE, EYE_R, pygame)

            pygame.display.flip()

        while _running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    _running = False
                    break
                # Permitir salir con Escape en desarrollo
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    _running = False
                    break

            now = time.time()

            with _lock:
                listening = _listening_mode
                desired   = _user_emotion
                idle      = (now - _last_msg_time) >= _IDLE_TIMEOUT

            # ── Modo escucha activa: mostrar imagen en lugar de ojos ──
            if listening:
                if _listen_surf is not None:
                    screen.blit(_listen_surf, (0, 0))
                else:
                    # Fallback visual si falta el asset
                    screen.fill((30, 60, 90))
                    font = pygame.font.SysFont(None, max(36, SCR_H // 15))
                    txt  = font.render("Escuchando...", True, (240, 240, 255))
                    screen.blit(txt, txt.get_rect(center=(SCR_W // 2, SCR_H // 2)))
                pygame.display.flip()
                clock.tick(60)
                continue

            if idle:
                desired = _IDLE_EMOTION

            # Arrancar transición si cambia la emoción deseada
            if desired != tr_to:
                if tr_active:
                    elapsed = now - tr_start
                    p       = _clamp(elapsed / TR_DUR, 0.0, 1.0)
                    if _smoothstep(p) >= 0.5:
                        tr_from = tr_to
                else:
                    tr_from = tr_to
                tr_to     = desired
                tr_start  = now
                tr_active = True

            if tr_active:
                p     = _clamp((now - tr_start) / TR_DUR, 0.0, 1.0)
                blend = _smoothstep(p)
                if p >= 1.0:
                    tr_active = False
                    tr_from   = tr_to
            else:
                blend = 1.0

            # Parpadeo
            if now >= next_blink and not blinking:
                blinking       = True
                blink_progress = 0.0

            if blinking:
                blink_progress += 0.08
                ratio = 1.0 - blink_progress if blink_progress <= 1.0 else blink_progress - 1.0
                draw_face(max(ratio, 0.0), tr_from, tr_to, blend, now)
                if blink_progress >= 2.0:
                    blinking   = False
                    next_blink = now + random.uniform(2, 4)
            else:
                draw_face(1.0, tr_from, tr_to, blend, now)

            clock.tick(60)

    except Exception as exc:
        print(f"[face] Error en el loop: {exc}")
    finally:
        try:
            pygame.quit()
        except Exception:
            pass
        print("[face] Ventana cerrada.")

