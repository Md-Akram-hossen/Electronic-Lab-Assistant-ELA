from __future__ import annotations

import logging
import re
from threading import Thread

from .agent import process_agent_command
from .audio import play_tts_response
from .config import get_groq_client, get_settings
from .inventory import (
    handle_borrow_component_flow,
    handle_return_component_flow,
    speak_component_availability,
    speak_component_list,
)
from .inventory_db import resolve_component_name
from .iot import publish_led
from .motion import collect_data, hand, left, leg, right
from .music import play_music, stop_music
from .parsing import normalize_command_for_console, parse_duration
from .self_learning import speak_what_i_learned
from .timers import cancel_all_timers, start_timer
from .vision import describe_scene, learn_face, learn_object, recognize_face, recognize_object
from .weather import get_weather

CUSTOM_RESPONSES = {
    "what is your name": "My name is ELA, I am an AI based humanoid robot.",
    "hello": "Hi there, it is glad to hear from you. I am ready to assist you and make your day brighter.",
    "how are you": "I have no emotion but I would be happy to make you happy.",
    "what can you do": "I can answer your questions, recognize speech, generate responses, and describe images.",
    "activate": "Hi there, it is glad to hear from you. I am ready to assist you and make your day brighter.",
}

BORROW_PATTERNS = [
    re.compile(r"\bi\s+want\s+to\s+g(?:e|a)r\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
    re.compile(r"\bi\s+want\s+to\s+get\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
    re.compile(r"\bwant\s+to\s+get\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
    re.compile(r"\bgive\s+me\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
    re.compile(r"\bi\s+need\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
]

RETURN_PATTERNS = [
    re.compile(r"\bi\s+want\s+to\s+return\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
    re.compile(r"\bwant\s+to\s+return\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
    re.compile(r"\breturn\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
]

AVAILABILITY_PATTERNS = [
    re.compile(r"\bhow\s+many\s+([a-z0-9 _-]+)\s+available\b", re.I),
    re.compile(r"\bcan\s+i\s+get\s+(?:an?\s+)?([a-z0-9 _-]+)\b", re.I),
    re.compile(r"\bwhere\s+i\s+can\s+get\s+(?:an?\s+)?([a-z0-9 _-]+)", re.I),
    re.compile(r"\bis\s+there\s+(?:any|an?|some)\s+([a-z0-9 _-]+)\s+available\b", re.I),
]

AGENT_KEYWORDS = (
    "email", "mail", "calendar", "calender", "appointment", "event",
    "note", "notes", "task", "tasks",
)


def _process_inventory_query(command: str) -> bool:
    lowered = command.lower()
    for pattern in AVAILABILITY_PATTERNS:
        match = pattern.search(lowered)
        if match:
            return speak_component_availability(match.group(1))
    if "list all components" in lowered:
        return speak_component_list()
    return False


def _process_borrow_return(command: str) -> bool:
    for pattern in BORROW_PATTERNS:
        match = pattern.search(command)
        if match:
            return handle_borrow_component_flow(resolve_component_name(match.group(1)))
    for pattern in RETURN_PATTERNS:
        match = pattern.search(command)
        if match:
            return handle_return_component_flow(resolve_component_name(match.group(1)))
    return False


def process_command(command: str) -> bool:
    display_text = normalize_command_for_console(command)
    logging.info("Detected command: %s", display_text)
    lowered = (command or "").lower()

    if _process_inventory_query(command):
        return True
    if _process_borrow_return(command):
        return True

    face_match = re.search(r"\blearn(?:ing)?\s+(?:person|face)[, ]+(?:this\s+is\s+)?([a-zA-Z0-9 _-]+)", command, re.I)
    if face_match:
        return learn_face(face_match.group(1).strip(" ()"))

    object_match = re.search(r"\blearn(?:ing)?\s+object[, ]+(?:that\s+is\s+)?([a-zA-Z0-9 _-]+)", command, re.I)
    if object_match:
        return learn_object(object_match.group(1).strip(" ()"))

    if re.search(r"\bwho\s+is\s+that\??", command, re.I):
        recognize_face()
        return True
    if re.search(r"\bwhat\s+is\s+that\??", command, re.I):
        recognize_object()
        return True
    if re.search(r"\bwhat\s+did\s+you\s+(?:self\s+)?learn\b", command, re.I):
        return speak_what_i_learned()

    if any(keyword in lowered for keyword in AGENT_KEYWORDS):
        return process_agent_command(command)

    if "weather" in lowered:
        match = re.search(r"\bweather\b.*?\bin\s+([a-z0-9 _-]+)\b", command, re.I)
        city = match.group(1).strip() if match else None
        play_tts_response(get_weather(city))
        return True

    if "data collection" in lowered or "collect data" in lowered:
        Thread(target=collect_data, daemon=True).start()
        return True

    if "hand movement" in lowered or "move hand" in lowered:
        Thread(target=hand, daemon=True).start()
        return True
    if "leg movement" in lowered or "go forward" in lowered or "leg move" in lowered:
        Thread(target=leg, daemon=True).start()
        return True
    if "right movement" in lowered or "go right" in lowered:
        Thread(target=right, daemon=True).start()
        return True
    if "left movement" in lowered or "go left" in lowered:
        Thread(target=left, daemon=True).start()
        return True

    if "set timer" in lowered or ("timer" in lowered and "set" in lowered):
        duration = parse_duration(command)
        if duration:
            start_timer(duration)
            play_tts_response(f"Timer set for {duration // 60} minutes and {duration % 60} seconds.")
        else:
            play_tts_response("Sorry, I couldn't understand the timer duration.")
        return True
    if "cancel timer" in lowered or "stop timer" in lowered:
        cancel_all_timers()
        return True

    if lowered in CUSTOM_RESPONSES:
        play_tts_response(CUSTOM_RESPONSES[lowered])
        return True

    if "turn on" in lowered and "light" in lowered:
        publish_led("ON")
        play_tts_response("LED turned on.")
        return True
    if "turn off" in lowered and "light" in lowered:
        publish_led("OFF")
        play_tts_response("LED turned off.")
        return True

    if "stop music" in lowered or ("music" in lowered and "stop" in lowered):
        stop_music()
        return True
    if "play" in lowered and ("music" in lowered or "song" in lowered):
        if "party" in lowered:
            play_music("party")
        elif "emotional" in lowered:
            play_music("emotional")
        elif "rock" in lowered:
            play_music("rock")
        elif "classical" in lowered:
            play_music("classical")
        elif "jazz" in lowered:
            play_music("jazz")
        else:
            play_music("general")
        return True

    if any(keyword in lowered for keyword in ["look", "picture", "what do you see", "see", "vision", "describe"]):
        play_tts_response(describe_scene())
        return True

    client = get_groq_client()
    settings = get_settings()
    if client is None:
        play_tts_response("Sorry, the chat model is not configured.")
        return True
    try:
        prompt = command if "give me detailed answer" in lowered else f"Give a concise answer in less than 150 words: {command}"
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=settings.groq_chat_model,
            temperature=0.7,
            max_tokens=1500 if "give me detailed answer" in lowered else 200,
        )
        play_tts_response((response.choices[0].message.content or "").strip())
    except Exception as exc:
        logging.error("Groq chat error: %s", exc)
        play_tts_response("Sorry, I couldn't process that request.")
    return True
