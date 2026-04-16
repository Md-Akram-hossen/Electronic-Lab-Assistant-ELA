from __future__ import annotations

import logging
from functools import lru_cache

import paho.mqtt.client as mqtt

from .config import get_settings


@lru_cache(maxsize=1)
def get_mqtt_client():
    settings = get_settings()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(settings.mqtt_broker, settings.mqtt_port)
        client.loop_start()
        logging.info("Connected to MQTT broker")
    except Exception as exc:
        logging.error("Failed to connect to MQTT broker: %s", exc)
    return client


def publish_led(state: str) -> None:
    settings = get_settings()
    get_mqtt_client().publish(settings.mqtt_topic_led, state)


def open_locker(locker_number: int) -> None:
    settings = get_settings()
    get_mqtt_client().publish(settings.mqtt_topic_locker, f"OPEN_LOCKER:{locker_number}")
