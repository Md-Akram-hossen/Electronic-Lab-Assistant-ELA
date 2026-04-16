from __future__ import annotations

import datetime as dt
import logging
import re
from zoneinfo import ZoneInfo

from .audio import get_audio_input, play_tts_response
from .config import get_settings
from .google_client import get_calendar_service, get_gmail_service
from .notes import add_item, delete_item_by_num, list_items


def _dt_to_rfc3339(value: dt.datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_time_24h(value: str) -> tuple[int, int] | None:
    match = re.search(r"\b(\d{1,2})(?::|\s+)?(\d{2})?\b", value or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _parse_day_only(value: str) -> int | None:
    value = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", (value or "").lower())
    match = re.search(r"\b(\d{1,2})\b", value)
    if not match:
        return None
    day = int(match.group(1))
    return day if 1 <= day <= 31 else None


def _parse_month_year(value: str) -> tuple[int, int] | None:
    months = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
        "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }
    tokens = re.sub(r"[,/\-]", " ", (value or "").lower()).split()
    month = None
    year = None
    for token in tokens:
        if token in months:
            month = months[token]
        elif token.isdigit():
            number = int(token)
            if number >= 2000:
                year = number
            elif month is None and 1 <= number <= 12:
                month = number
            elif number <= 99:
                year = 2000 + number
    if month and year:
        return month, year
    return None


def _calendar_upcoming(max_results: int = 10):
    settings = get_settings()
    service = get_calendar_service()
    if not service:
        return []
    now = dt.datetime.now(ZoneInfo(settings.default_tz))
    return service.events().list(
        calendarId="primary",
        timeMin=_dt_to_rfc3339(now),
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute().get("items", [])


def _calendar_slot_is_free(start_dt: dt.datetime, end_dt: dt.datetime) -> bool:
    service = get_calendar_service()
    if not service:
        return False
    items = service.events().list(
        calendarId="primary",
        timeMin=_dt_to_rfc3339(start_dt),
        timeMax=_dt_to_rfc3339(end_dt),
        singleEvents=True,
        orderBy="startTime",
        maxResults=10,
    ).execute().get("items", [])
    return len(items) == 0


def _calendar_add_event(title: str, start_dt: dt.datetime, end_dt: dt.datetime) -> bool:
    settings = get_settings()
    service = get_calendar_service()
    if not service:
        return False
    body = {
        "summary": title,
        "start": {"dateTime": _dt_to_rfc3339(start_dt), "timeZone": settings.default_tz},
        "end": {"dateTime": _dt_to_rfc3339(end_dt), "timeZone": settings.default_tz},
    }
    service.events().insert(calendarId="primary", body=body).execute()
    return True


def _calendar_cancel_by_title(title_substring: str) -> int:
    settings = get_settings()
    service = get_calendar_service()
    if not service:
        return 0
    now = dt.datetime.now(ZoneInfo(settings.default_tz)) - dt.timedelta(days=1)
    items = service.events().list(
        calendarId="primary",
        timeMin=_dt_to_rfc3339(now),
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
        q=title_substring,
    ).execute().get("items", [])
    deleted = 0
    for event in items:
        summary = (event.get("summary") or "").lower()
        if title_substring.lower() in summary:
            service.events().delete(calendarId="primary", eventId=event["id"]).execute()
            deleted += 1
    return deleted


def _gmail_recent_subjects(max_results: int = 5, subject_count: int = 3):
    service = get_gmail_service()
    if not service:
        return None
    messages = service.users().messages().list(userId="me", maxResults=max_results).execute().get("messages", [])
    subjects = []
    for message in messages[:subject_count]:
        metadata = service.users().messages().get(
            userId="me",
            id=message["id"],
            format="metadata",
            metadataHeaders=["Subject"],
        ).execute()
        headers = metadata.get("payload", {}).get("headers", [])
        subject = next((header.get("value") for header in headers if (header.get("name") or "").lower() == "subject"), "(no subject)")
        subjects.append(subject)
    return {"count": len(messages), "subjects": subjects}


def process_agent_command(command: str) -> bool:
    text = (command or "").strip().lower()

    note_match = re.search(r"\b(?:add|include)\s+note(?:s)?\b(.*)", text)
    if note_match:
        note_text = note_match.group(1).strip(" .,:;-")
        if note_text:
            number = add_item("notes", note_text)
            play_tts_response(f"Saved note {number}." if number else "Sorry, I could not save the note.")
        else:
            play_tts_response("Please say the note text after add note.")
        return True

    task_match = re.search(r"\b(?:add|include)\s+task(?:s)?\b(.*)", text)
    if task_match:
        task_text = task_match.group(1).strip(" .,:;-")
        if task_text:
            number = add_item("tasks", task_text)
            play_tts_response(f"Saved task {number}." if number else "Sorry, I could not save the task.")
        else:
            play_tts_response("Please say the task text after add task.")
        return True

    if "review my notes" in text or "what's on my notes" in text or "whats on my notes" in text:
        rows = list_items("notes", limit=5)
        if not rows:
            play_tts_response("You have no notes.")
        else:
            play_tts_response(" . ".join(f"Note {num}: {content}" for num, content, _ in rows))
        return True

    if "review my tasks" in text or "what's on my tasks" in text or "whats on my tasks" in text:
        rows = list_items("tasks", limit=5)
        if not rows:
            play_tts_response("You have no tasks.")
        else:
            play_tts_response(" . ".join(f"Task {num}: {content}" for num, content, _ in rows))
        return True

    match = re.search(r"\b(?:remove|delete|detete)\s+note(?:s)?\s+(\d+)\b", text)
    if match:
        num = int(match.group(1))
        play_tts_response(f"Note {num} removed." if delete_item_by_num("notes", num) else f"I could not find note {num}.")
        return True

    match = re.search(r"\b(?:remove|delete|detete)\s+task(?:s)?\s+(\d+)\b", text)
    if match:
        num = int(match.group(1))
        play_tts_response(f"Task {num} removed." if delete_item_by_num("tasks", num) else f"I could not find task {num}.")
        return True

    if "review my calendar" in text or "review my calender" in text or "what's on my calendar" in text or "what's on my calender" in text:
        items = _calendar_upcoming()
        if not items:
            play_tts_response("You have no upcoming calendar events.")
        else:
            preview = items[:3]
            parts = []
            for event in preview:
                start = event.get("start", {})
                start_text = start.get("dateTime") or start.get("date") or ""
                parts.append(f"{event.get('summary', 'Untitled event')} at {start_text}")
            play_tts_response(f"You have {len(items)} upcoming events. " + " . ".join(parts))
        return True

    if "set calendar event" in text or "set calender event" in text:
        settings = get_settings()
        play_tts_response("Please say the day number only.")
        day = _parse_day_only(get_audio_input() or "")
        if not day:
            play_tts_response("Sorry, I could not understand the day.")
            return True
        play_tts_response("Now say the month and year.")
        month_year = _parse_month_year(get_audio_input() or "")
        if not month_year:
            play_tts_response("Sorry, I could not understand the month and year.")
            return True
        play_tts_response("What time? Please say in 24 hour format.")
        time_value = _parse_time_24h(get_audio_input() or "")
        if not time_value:
            play_tts_response("Sorry, I could not understand the time.")
            return True
        play_tts_response("What is the title of the event?")
        title = (get_audio_input() or "").strip()
        if not title:
            play_tts_response("Sorry, I did not catch the title.")
            return True
        month, year = month_year
        hour, minute = time_value
        try:
            date_value = dt.date(year, month, day)
        except Exception:
            play_tts_response("That date is not valid.")
            return True
        start_dt = dt.datetime(date_value.year, date_value.month, date_value.day, hour, minute, tzinfo=ZoneInfo(settings.default_tz))
        end_dt = start_dt + dt.timedelta(hours=1)
        if not _calendar_slot_is_free(start_dt, end_dt):
            play_tts_response("Sorry, the schedule already booked.")
            return True
        ok = _calendar_add_event(title, start_dt, end_dt)
        play_tts_response(f"Event added. {title} on {date_value.isoformat()} at {hour:02d}:{minute:02d}." if ok else "Sorry, I could not add the event.")
        return True

    if text.startswith("cancel") and "event" in text:
        title = text.split("event", 1)[1].strip()
        if not title:
            play_tts_response("Please say the event title you want to cancel.")
            return True
        deleted = _calendar_cancel_by_title(title)
        play_tts_response(f"Cancelled {deleted} event(s) matching {title}." if deleted else f"I could not find any event matching {title}.")
        return True

    if "review my email" in text or "what's on my email" in text or "whats on my email" in text or "review my mail" in text:
        data = _gmail_recent_subjects()
        if not data:
            play_tts_response("Gmail not configured.")
            return True
        subjects = data["subjects"]
        if not subjects:
            play_tts_response("You have no recent emails.")
            return True
        parts = [f"{index + 1}, {subject}" for index, subject in enumerate(subjects)]
        play_tts_response(f"You have {data['count']} recent emails. The latest subjects are: " + ". ".join(parts))
        return True

    play_tts_response("Sorry, I didn't recognize that agent request.")
    return True
