from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from .audio import play_tts_response
from .camera import capture_image_to
from .config import get_settings

try:
    import RPi.GPIO as GPIO
except Exception:
    GPIO = None

try:
    from board import SCL, SDA
    import busio
    from adafruit_pca9685 import PCA9685
except Exception:
    SCL = SDA = busio = PCA9685 = None


def vision_servo_scan() -> None:
    settings = get_settings()
    if GPIO is None:
        return
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(settings.servo_pin, GPIO.OUT)
        servo = GPIO.PWM(settings.servo_pin, 50)
        servo.start(settings.servo_center_angle)
        time.sleep(1)
        servo.ChangeDutyCycle(settings.servo_left_angle)
        time.sleep(settings.servo_delay)
        servo.ChangeDutyCycle(settings.servo_right_angle)
        time.sleep(settings.servo_delay)
        servo.ChangeDutyCycle(settings.servo_center_angle)
        time.sleep(settings.servo_delay)
    except Exception as exc:
        logging.error("Servo movement error: %s", exc)
    finally:
        try:
            servo.stop()
        except Exception:
            pass
        try:
            GPIO.setup(settings.servo_pin, GPIO.IN)
        except Exception:
            pass


def collect_data() -> None:
    settings = get_settings()
    save_dir = settings.base_dir / "data_capture"
    save_dir.mkdir(parents=True, exist_ok=True)
    if GPIO is None:
        play_tts_response("GPIO is not available.")
        return
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(settings.servo_pin, GPIO.OUT)
        servo = GPIO.PWM(settings.servo_pin, 50)
        servo.start(settings.servo_center_angle)
        time.sleep(1)
        for label, duty in {"0": 5, "90": 7.5, "180": 10}.items():
            servo.ChangeDutyCycle(duty)
            time.sleep(1)
            capture_image_to(save_dir / f"image_{label}.jpg")
        servo.ChangeDutyCycle(settings.servo_center_angle)
        time.sleep(1)
        play_tts_response("Data tasks complete. Images saved.")
    except Exception as exc:
        logging.error("Data collection error: %s", exc)
        play_tts_response("Sorry, data collection failed.")
    finally:
        try:
            servo.stop()
        except Exception:
            pass
        try:
            GPIO.setup(settings.servo_pin, GPIO.IN)
        except Exception:
            pass


def _angle_to_duty_cycle(angle: float, freq_hz: int = 50) -> int:
    angle = max(0.0, min(180.0, float(angle)))
    pulse_us = 500 + (angle / 180.0) * 2000
    period_us = 1_000_000.0 / freq_hz
    return int((pulse_us / period_us) * 0xFFFF)


def _with_pca():
    if busio is None or PCA9685 is None:
        raise RuntimeError("PCA9685 stack is not available")
    i2c = busio.I2C(SCL, SDA)
    pca = PCA9685(i2c)
    pca.frequency = 50
    return pca


def hand() -> None:
    try:
        pca = _with_pca()
        sequence = [90, 120, 150, 90]
        for _ in range(3):
            for angle in sequence:
                duty = _angle_to_duty_cycle(angle)
                pca.channels[0].duty_cycle = duty
                pca.channels[1].duty_cycle = _angle_to_duty_cycle(180 - angle)
                time.sleep(0.4)
        play_tts_response("Hand task complete.")
    except Exception as exc:
        logging.error("Hand movement error: %s", exc)
        play_tts_response("Sorry, hand movement failed.")
    finally:
        try:
            pca.deinit()
        except Exception:
            pass


def leg() -> None:
    try:
        pca = _with_pca()
        for _ in range(5):
            for channel, target in ((4, 50), (5, 90), (4, 30), (5, 30)):
                pca.channels[channel].duty_cycle = _angle_to_duty_cycle(target)
                time.sleep(0.4)
        play_tts_response("Leg task complete.")
    except Exception as exc:
        logging.error("Leg movement error: %s", exc)
        play_tts_response("Sorry, leg movement failed.")
    finally:
        try:
            pca.deinit()
        except Exception:
            pass


def move_pair(channel_a: int, channel_b: int, target_angle: float, completion_text: str) -> None:
    try:
        pca = _with_pca()
        base = 90.0
        for _ in range(5):
            for angle in (base, target_angle, base):
                duty = _angle_to_duty_cycle(angle)
                pca.channels[channel_a].duty_cycle = duty
                pca.channels[channel_b].duty_cycle = duty
                time.sleep(0.3)
        play_tts_response(completion_text)
    except Exception as exc:
        logging.error("Pair movement error: %s", exc)
        play_tts_response("Sorry, movement failed.")
    finally:
        try:
            pca.deinit()
        except Exception:
            pass


def right() -> None:
    move_pair(12, 13, 120, "Right movement completed.")


def left() -> None:
    move_pair(12, 13, 60, "Left movement completed.")
