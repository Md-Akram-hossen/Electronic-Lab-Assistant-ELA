from __future__ import annotations

import time
from threading import Event, Lock

mouth_talking = Event()
camera_lock = Lock()
groq_lock = Lock()
selflearn_lock = Lock()
robot_state_lock = Lock()
active_timer_lock = Lock()

active_timer_remaining: int | None = None

ROBOT_STATE = {
    "is_active": False,
    "sleep_since": None,
}


def set_robot_active(active: bool) -> None:
    now = time.time()
    with robot_state_lock:
        prev = ROBOT_STATE["is_active"]
        ROBOT_STATE["is_active"] = bool(active)
        if active:
            ROBOT_STATE["sleep_since"] = None
        elif prev and ROBOT_STATE["sleep_since"] is None:
            ROBOT_STATE["sleep_since"] = now


def get_robot_state() -> tuple[bool, float | None]:
    with robot_state_lock:
        return bool(ROBOT_STATE["is_active"]), ROBOT_STATE["sleep_since"]


def set_active_timer_remaining(value: int | None) -> None:
    global active_timer_remaining
    with active_timer_lock:
        active_timer_remaining = value


def get_active_timer_remaining() -> int | None:
    with active_timer_lock:
        return active_timer_remaining
