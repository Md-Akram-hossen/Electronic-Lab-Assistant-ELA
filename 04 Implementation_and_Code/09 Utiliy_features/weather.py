from __future__ import annotations

import logging
from typing import Optional

import requests


def get_weather(city_name: Optional[str] = None) -> str:
    degree = "\N{DEGREE SIGN}"
    city = (city_name or "").strip()
    if not city or city.lower() in {"your location", "my location", "here", "auto"}:
        city = "autoip"
    try:
        response = requests.get(
            f"https://wttr.in/{city}",
            params={"format": "j1"},
            timeout=8,
            headers={"User-Agent": "ela-weather/1.0"},
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        data = response.json()
        current = (data.get("current_condition") or [{}])[0]
        description = ((current.get("weatherDesc") or [{"value": "unknown"}])[0].get("value")) or "unknown"
        temp_c = current.get("temp_C")
        feels_like = current.get("FeelsLikeC")
        humidity = current.get("humidity")
        area = ""
        try:
            area = ((data.get("nearest_area") or [{}])[0].get("areaName") or [{}])[0].get("value") or ""
        except Exception:
            area = ""
        parts = [f"The weather{' in ' + area if area else ''} is {description}"]
        if temp_c is not None:
            parts[0] += f" with {temp_c}{degree}C"
        if feels_like is not None:
            parts.append(f"Feels like {feels_like}{degree}C")
        if humidity is not None:
            parts.append(f"Humidity {humidity}%")
        return ". ".join(parts) + "."
    except Exception as exc:
        logging.error("Weather fetch error: %s", exc)
        return "Sorry, I couldn't get the weather right now."
