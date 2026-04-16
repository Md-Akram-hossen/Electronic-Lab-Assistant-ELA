from __future__ import annotations

import re
from typing import Optional

WAKE_RE = re.compile(r"\b(?:ela|ella)\b", re.I)

_NUM_WORDS = {
    "zero": 0, "oh": 0, "o": 0,
    "one": 1, "a": 1, "an": 1,
    "two": 2, "too": 2, "to": 2,
    "three": 3,
    "four": 4, "for": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8, "ate": 8,
    "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000, "couple": 2, "few": 3, "dozen": 12,
}

_DIGIT_WORD = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1",
    "two": "2", "too": "2", "to": "2",
    "three": "3",
    "four": "4", "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8", "ate": "8",
    "nine": "9",
}

_QTY_MISHEAR_MAP = {
    "fine": "five", "file": "five", "fife": "five", "fire": "five",
    "hive": "five", "vive": "five", "wife": "five",
    "tree": "three", "free": "three",
    "sex": "six", "sicks": "six",
    "fore": "four",
    "won": "one",
}

COMPONENT_ALIASES = {
    "arduino": {"arduino", "arena", "ardeno", "audio", "aldi", "aadu", "odd"},
    "servo": {"servo", "tervo", "sevo", "turbo", "tevo", "sebo"},
    "seven segment": {
        "seven segment", "7 segment", "7 seg", "seven seg",
        "seven segment display", "7 segment display", "7-segment",
        "segment display", "sigment display",
    },
    "display": {"display", "dis play", "dplay"},
}

_ALIAS_TO_CANON = {}
for canon, aliases in COMPONENT_ALIASES.items():
    for alias in aliases:
        cleaned = re.sub(r"[^a-z0-9\s-]", "", alias.lower()).replace("-", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            _ALIAS_TO_CANON[cleaned] = canon

_AMBIGUOUS_SINGLETON_ALIASES = {"play", "dis"}

_NON_COMPONENT_KEYWORDS = (
    "music", "song", "timer", "weather", "open", "door", "learn", "learning",
    "face", "object", "look", "picture", "vision", "hand", "leg", "data",
    "light", "led", "email", "mail", "calendar", "appointment", "event",
    "note", "notes", "remind", "schedule",
)


def wake_word_detected(text: str | None) -> bool:
    return bool(text and WAKE_RE.search(text))


def extract_command(text: str | None) -> str:
    if not text:
        return ""
    return WAKE_RE.sub("", text, count=1).strip()


def clean_tokens(text: str) -> list[str]:
    normalized = (text or "").lower().replace("-", " ")
    normalized = re.sub(r"[,/\.]", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    return [token for token in normalized.split() if token]


def parse_id_digits(text: str | None) -> Optional[str]:
    if not text:
        return None
    digits = re.findall(r"\d", text)
    if digits:
        return "".join(digits)
    out = [_DIGIT_WORD[token] for token in clean_tokens(text) if token in _DIGIT_WORD]
    return "".join(out) if out else None


def parse_quantity_digits(text: str | None) -> Optional[int]:
    if not text:
        return None
    direct = re.search(r"\d+", text)
    if direct:
        return int(direct.group(0))
    digits: list[str] = []
    for token in clean_tokens(text):
        if token in _DIGIT_WORD:
            digits.append(_DIGIT_WORD[token])
        elif digits:
            break
    return int("".join(digits)) if digits else None


def _words_to_int(tokens: list[str]) -> Optional[int]:
    total = 0
    current = 0
    for token in tokens:
        if token == "hundred":
            current = max(1, current) * 100
        elif token == "thousand":
            current = max(1, current) * 1000
            total += current
            current = 0
        elif token in _NUM_WORDS and _NUM_WORDS[token] < 100:
            value = _NUM_WORDS[token]
            if current >= 20 and current % 10 == 0 and value < 10:
                current += value
            else:
                current += value
        else:
            total += current
            current = 0
    total += current
    return total if total > 0 else None


def parse_spoken_quantity(text: str | None) -> Optional[int]:
    if not text:
        return None
    direct = re.search(r"\d+", text)
    if direct:
        return int(direct.group(0))
    tokens = clean_tokens(text)
    for token in tokens:
        if token in {"couple", "few", "dozen"}:
            return _NUM_WORDS[token]
    number_tokens = [token for token in tokens if token in _NUM_WORDS or token in {"hundred", "thousand"}]
    return _words_to_int(number_tokens) if number_tokens else None


def parse_component_quantity(text: str | None) -> Optional[int]:
    if not text:
        return None
    value = parse_spoken_quantity(text)
    if value is not None:
        return value
    value = parse_quantity_digits(text)
    if value is not None:
        return value
    fixed = " ".join(_QTY_MISHEAR_MAP.get(token, token) for token in clean_tokens(text))
    return parse_spoken_quantity(fixed) or parse_quantity_digits(fixed)


def parse_duration(text: str | None) -> Optional[int]:
    if not text:
        return None
    minutes = re.search(r"(\d+)\s*(minute|minutes|min)", text, re.I)
    seconds = re.search(r"(\d+)\s*(second|seconds|sec)", text, re.I)
    total = 0
    if minutes:
        total += int(minutes.group(1)) * 60
    if seconds:
        total += int(seconds.group(1))
    return total or None


def clean_component_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s-]", "", (text or "").lower()).replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^(a|an|the)\s+", "", cleaned)
    return cleaned.strip()


def normalize_component_name(text: str) -> str:
    cleaned = clean_component_text(text)
    if cleaned in _ALIAS_TO_CANON:
        return _ALIAS_TO_CANON[cleaned]
    for alias in sorted(_ALIAS_TO_CANON, key=len, reverse=True):
        if " " in alias and re.search(rf"(^|\s){re.escape(alias)}(\s|$)", cleaned):
            return _ALIAS_TO_CANON[alias]
    return cleaned


def looks_like_component_only_command(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(keyword in lowered for keyword in _NON_COMPONENT_KEYWORDS):
        return False
    cleaned = clean_component_text(lowered)
    if not cleaned:
        return False
    if cleaned in _AMBIGUOUS_SINGLETON_ALIASES and len(cleaned.split()) == 1:
        return False
    return len(cleaned.split()) <= 3


def normalize_command_for_console(text: str) -> str:
    if not text:
        return text
    normalized = clean_component_text(text)
    for alias in sorted(_ALIAS_TO_CANON, key=len, reverse=True):
        if alias in _AMBIGUOUS_SINGLETON_ALIASES and " " not in alias:
            continue
        normalized = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", _ALIAS_TO_CANON[alias], normalized)
    return re.sub(r"\s+", " ", normalized).strip()
