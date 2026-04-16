from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from groq import Groq
except Exception:
    Groq = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    faces_dir: Path
    objects_dir: Path
    music_dir: Path
    self_learn_dir: Path
    notes_db: Path
    lab_db: Path
    self_learn_db: Path
    credentials_path: Path
    token_path: Path
    components_xlsx: Path
    students_xlsx: Path
    borrowed_all_xlsx: Path
    borrowed_by_item_dir: Path
    audio_mp3: Path
    audio_wav: Path
    default_tz: str
    wake_words: tuple[str, ...]
    active_duration: int
    groq_chat_model: str
    groq_vision_model: str
    mqtt_broker: str
    mqtt_port: int
    mqtt_topic_led: str
    mqtt_topic_locker: str
    servo_pin: int
    servo_left_angle: float
    servo_right_angle: float
    servo_center_angle: float
    servo_delay: float
    face_match_threshold: float
    object_min_good_matches: int
    borrow_due_months: int
    overdue_check_interval_hours: int
    overdue_reminder_min_days: int
    self_learn_enabled: bool
    self_learn_sleep_delay_sec: int
    self_learn_interval_sec: int
    self_learn_max_objects: int
    self_learn_match_max: int
    self_learn_hash_strict: int
    self_learn_hash_loose: int
    face_hash_strict: int
    face_hash_loose: int
    object_hash_strict: int
    object_hash_loose: int
    groq_api_key: Optional[str]
    lab_email: str

    @classmethod
    def from_env(cls) -> "Settings":
        package_dir = Path(__file__).resolve().parent
        base_dir = package_dir.parent
        data_dir = base_dir / "data"
        return cls(
            base_dir=base_dir,
            data_dir=data_dir,
            faces_dir=data_dir / "faces",
            objects_dir=data_dir / "objects",
            music_dir=base_dir / "music",
            self_learn_dir=data_dir / "selflearn",
            notes_db=base_dir / "ELA_notes.db",
            lab_db=base_dir / "lab_assets.db",
            self_learn_db=base_dir / "ELA_selflearn.db",
            credentials_path=base_dir / "credentials.json",
            token_path=base_dir / "token.json",
            components_xlsx=base_dir / "components.xlsx",
            students_xlsx=base_dir / "students.xlsx",
            borrowed_all_xlsx=base_dir / "borrowed_components.xlsx",
            borrowed_by_item_dir=base_dir / "borrowed_by_item",
            audio_mp3=base_dir / "response.mp3",
            audio_wav=base_dir / "response.wav",
            default_tz="Europe/Berlin",
            wake_words=("ela", "ella"),
            active_duration=60,
            groq_chat_model="llama-3.3-70b-versatile",
            groq_vision_model="meta-llama/llama-4-scout-17b-16e-instruct",
            mqtt_broker=os.getenv("ELA_MQTT_BROKER", "192.168.0.218"),
            mqtt_port=int(os.getenv("ELA_MQTT_PORT", "1883")),
            mqtt_topic_led="robot/led",
            mqtt_topic_locker="robot/locker",
            servo_pin=17,
            servo_left_angle=5.0,
            servo_right_angle=10.0,
            servo_center_angle=7.5,
            servo_delay=0.8,
            face_match_threshold=0.60,
            object_min_good_matches=25,
            borrow_due_months=2,
            overdue_check_interval_hours=12,
            overdue_reminder_min_days=7,
            self_learn_enabled=True,
            self_learn_sleep_delay_sec=5 * 60,
            self_learn_interval_sec=20 * 60,
            self_learn_max_objects=5,
            self_learn_match_max=3,
            self_learn_hash_strict=24,
            self_learn_hash_loose=55,
            face_hash_strict=30,
            face_hash_loose=60,
            object_hash_strict=28,
            object_hash_loose=58,
            groq_api_key=os.getenv("GROQ_API_KEY"),
            lab_email=os.getenv("ELA_LAB_EMAIL", "md.hshl.de@gmail.com"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings.from_env()
    for path in (
        settings.data_dir,
        settings.faces_dir,
        settings.objects_dir,
        settings.music_dir,
        settings.music_dir / "general",
        settings.self_learn_dir,
        settings.borrowed_by_item_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return settings


@lru_cache(maxsize=1)
def get_groq_client():
    settings = get_settings()
    if not settings.groq_api_key or Groq is None:
        return None
    return Groq(api_key=settings.groq_api_key)
