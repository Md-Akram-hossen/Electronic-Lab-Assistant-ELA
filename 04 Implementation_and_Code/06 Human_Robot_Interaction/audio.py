from __future__ import annotations

import logging
import subprocess

import gtts
import speech_recognition as sr
from pydub import AudioSegment
from pydub.utils import which

from .config import get_settings
from .state import mouth_talking

AudioSegment.converter = which("ffmpeg")


def play_tts_response(text: str) -> None:
    settings = get_settings()
    try:
        tts = gtts.gTTS(text=text, lang="en", slow=False)
        tts.save(str(settings.audio_mp3))
        audio = AudioSegment.from_mp3(str(settings.audio_mp3))
        audio.export(str(settings.audio_wav), format="wav")
        mouth_talking.set()
        subprocess.run(
            ["pw-play", str(settings.audio_wav)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception as exc:
        logging.error("TTS error: %s", exc)
    finally:
        mouth_talking.clear()


def get_audio_input(timeout: int = 5, phrase_time_limit: int = 5) -> str | None:
    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        return recognizer.recognize_google(audio).lower()
    except Exception:
        return None
