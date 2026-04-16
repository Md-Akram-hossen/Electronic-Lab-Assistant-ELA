from __future__ import annotations

import time
from threading import Lock, Thread
from uuid import uuid4

from .audio import play_tts_response
from .state import get_active_timer_remaining, set_active_timer_remaining

timers: dict[str, Thread] = {}
timer_lock = Lock()


def start_timer(duration: int) -> str:
    timer_id = str(uuid4())

    def worker() -> None:
        set_active_timer_remaining(duration)
        while True:
            remaining = get_active_timer_remaining()
            if remaining is None or remaining <= 0:
                break
            time.sleep(1)
            set_active_timer_remaining(remaining - 1)
        play_tts_response("Time is up!")
        with timer_lock:
            timers.pop(timer_id, None)

    thread = Thread(target=worker, daemon=True)
    with timer_lock:
        timers[timer_id] = thread
    thread.start()
    return timer_id


def cancel_all_timers() -> None:
    with timer_lock:
        timers.clear()
    set_active_timer_remaining(None)
    play_tts_response("All timers cancelled.")
