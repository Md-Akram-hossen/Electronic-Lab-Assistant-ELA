from __future__ import annotations

import random
import time
from threading import Lock
from typing import Optional

from .audio import get_audio_input, play_tts_response
from .google_client import send_simple_email
from .parsing import parse_id_digits

_otp_store: dict[str, dict[str, float]] = {}
_otp_lock = Lock()
_OTP_TTL_SECONDS = 300


def set_otp(student_id: str, otp: str) -> None:
    with _otp_lock:
        _otp_store[student_id] = {"otp": otp, "exp": time.time() + _OTP_TTL_SECONDS}


def get_otp(student_id: str) -> Optional[str]:
    with _otp_lock:
        record = _otp_store.get(student_id)
        if not record:
            return None
        if record["exp"] < time.time():
            _otp_store.pop(student_id, None)
            return None
        return str(record["otp"])


def generate_and_send_otp(student_id: str, student_name: str, email: str) -> bool:
    if not email:
        play_tts_response("Your email is not registered. Please contact the lab supervisor.")
        return False
    otp = f"{random.randint(1000, 9999)}"
    set_otp(student_id, otp)
    subject = f"Your Lab OTP: {otp}"
    body = (
        f"Hello {student_name},\n\n"
        f"Your one-time password for lab locker access is: {otp}\n"
        f"This code expires in 5 minutes.\n\n"
        f"Requested by ELA."
    )
    ok, _ = send_simple_email(email, subject, body)
    if not ok:
        play_tts_response("Sorry, I could not send the verification code to your email.")
    return ok


def verify_spoken_otp(student_id: str, max_attempts: int = 2) -> bool:
    for attempt in range(max_attempts):
        play_tts_response("Please say the four digit verification code.")
        spoken = get_audio_input()
        digits = parse_id_digits(spoken or "")
        otp = get_otp(student_id)
        if not otp:
            play_tts_response("The verification code expired.")
            return False
        if digits == otp:
            return True
        if attempt < max_attempts - 1:
            play_tts_response("That does not match. Try again.")
    return False
