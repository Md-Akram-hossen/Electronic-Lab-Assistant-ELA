from __future__ import annotations

import logging
import random
import time
from threading import Thread

from PIL import ImageFont

from .state import get_active_timer_remaining, mouth_talking

try:
    from luma.core.interface.serial import spi
    from luma.oled.device import sh1106
    from luma.core.render import canvas
    try:
        from luma.core.interface.gpio import lgpio as luma_lgpio
        HAS_LGPIO = True
    except Exception:
        HAS_LGPIO = False
        luma_lgpio = None
except Exception:
    spi = sh1106 = canvas = None
    HAS_LGPIO = False
    luma_lgpio = None


def init_oled():
    if spi is None or sh1106 is None:
        return None
    try:
        if HAS_LGPIO:
            gpio = luma_lgpio()
            serial_interface = spi(port=0, device=0, gpio=gpio, gpio_DC=25, gpio_RST=24)
        else:
            serial_interface = spi(port=0, device=0, gpio_DC=25, gpio_RST=24)
        return sh1106(serial_interface, rotate=0)
    except Exception as exc:
        logging.error("OLED init failed: %s", exc)
        return None


def oled_display_loop() -> None:
    device = init_oled()
    if device is None or canvas is None:
        while True:
            time.sleep(5)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
    except Exception:
        font = ImageFont.load_default()
    blink_interval = 3
    last_blink = time.time()
    while True:
        now = time.time()
        with canvas(device) as draw:
            if now - last_blink > blink_interval:
                draw.rectangle((10, 20, 50, 50), fill="black")
                draw.rectangle((70, 20, 110, 50), fill="black")
                time.sleep(0.2)
                last_blink = now
            else:
                draw.ellipse((10, 20, 50, 50), outline="white", fill="white")
                draw.ellipse((25, 30, 35, 40), outline="black", fill="black")
                draw.ellipse((70, 20, 110, 50), outline="white", fill="white")
                draw.ellipse((85, 30, 95, 40), outline="black", fill="black")
            if mouth_talking.is_set():
                height = random.randint(5, 15)
                draw.rectangle((45, 55, 75, 55 + height), fill="white")
            else:
                draw.rectangle((45, 60, 75, 62), fill="white")
            remaining = get_active_timer_remaining()
            if remaining:
                minutes, seconds = divmod(remaining, 60)
                draw.text((95, 0), f"{minutes}:{seconds:02d}", font=font, fill="white")
        time.sleep(0.1)


def start_oled_thread() -> Thread:
    thread = Thread(target=oled_display_loop, daemon=True)
    thread.start()
    return thread
