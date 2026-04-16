from __future__ import annotations

import logging
import time
from threading import Thread

from .audio import get_audio_input, play_tts_response
from .commands import process_command
from .config import get_settings
from .display import start_oled_thread
from .inventory_db import ensure_lab_db, overdue_reminder_loop, seed_defaults_if_empty
from .notes import ensure_notes_db
from .parsing import extract_command, wake_word_detected
from .self_learning import ensure_selflearn_db, rebuild_selflearn_index, self_discovery_loop
from .state import set_robot_active
from .vision import init_learning_indexes


def init_boot() -> None:
    get_settings()
    ensure_notes_db()
    ensure_lab_db()
    seed_defaults_if_empty()
    ensure_selflearn_db()
    init_learning_indexes()
    rebuild_selflearn_index()
    start_oled_thread()
    Thread(target=overdue_reminder_loop, daemon=True).start()
    Thread(target=self_discovery_loop, daemon=True).start()


def run() -> None:
    settings = get_settings()
    init_boot()
    logging.info("Starting ELA. Say 'Ela' to activate me.")
    last_activity_time = 0.0
    is_active = False
    set_robot_active(False)
    try:
        while True:
            now = time.time()
            if is_active and (now - last_activity_time > settings.active_duration):
                is_active = False
                set_robot_active(False)
                play_tts_response("Going to sleep. Say Ela when you need me.")
                logging.info("Sleep mode")
            user_input = get_audio_input()
            if user_input:
                logging.info("Heard: %s", user_input)
                last_activity_time = now
                if is_active or wake_word_detected(user_input):
                    if not is_active:
                        is_active = True
                        set_robot_active(True)
                        logging.info("Active mode")
                    command = extract_command(user_input) if wake_word_detected(user_input) else user_input
                    if command:
                        if process_command(command):
                            last_activity_time = time.time()
                    else:
                        play_tts_response("Yes? How can I help you?")
                        follow_up = get_audio_input()
                        if follow_up and process_command(follow_up):
                            last_activity_time = time.time()
                else:
                    logging.info("Wake word not detected; ignoring")
            else:
                time.sleep(0.5)
    except KeyboardInterrupt:
        logging.info("Program terminated by user")


if __name__ == "__main__":
    run()
