from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import time
from pathlib import Path
from threading import Lock

from .audio import play_tts_response
from .camera import capture_image_to, encode_image
from .config import get_groq_client, get_settings
from .state import get_robot_state, groq_lock, selflearn_lock
from .vision import average_hash_int, hamming

selflearn_cache = {"ts_utc": None, "objects": []}
selflearn_cache_lock = Lock()
selflearn_index: list[dict] = []
selflearn_index_lock = Lock()


def ensure_selflearn_db() -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.self_learn_db)
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS selflearn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            image_path TEXT,
            objects_json TEXT NOT NULL
        )
        '''
    )
    conn.commit()
    conn.close()


def selflearn_add(ts_utc: str, image_path: str, objects: list[dict]) -> None:
    settings = get_settings()
    with selflearn_lock:
        conn = sqlite3.connect(settings.self_learn_db)
        conn.execute(
            "INSERT INTO selflearn(ts_utc, image_path, objects_json) VALUES(?,?,?)",
            (ts_utc, image_path, json.dumps(objects, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()


def selflearn_latest(limit: int = 1):
    settings = get_settings()
    with selflearn_lock:
        conn = sqlite3.connect(settings.self_learn_db)
        rows = conn.execute(
            "SELECT ts_utc, image_path, objects_json FROM selflearn ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        conn.close()
    return rows


def extract_json_obj(text: str) -> dict | None:
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    import re
    match = re.search(r"\{.*\}", text or "", flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def capture_image_selflearn() -> Path | None:
    settings = get_settings()
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = settings.self_learn_dir / f"selflearn_{timestamp}.jpg"
    return capture_image_to(target)


def groq_object_discovery(image_path: str | Path) -> list[dict]:
    client = get_groq_client()
    settings = get_settings()
    if client is None:
        return []
    prompt = (
        "Identify up to five distinct visible objects. "
        "Return strict JSON: {\"objects\":[{\"name\":\"...\",\"use\":\"...\"}]}"
    )
    try:
        with groq_lock:
            response = client.chat.completions.create(
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image(image_path)}"}},
                    ],
                }],
                model=settings.groq_vision_model,
                temperature=0.0,
                max_tokens=250,
            )
        content = (response.choices[0].message.content or "").strip()
        data = extract_json_obj(content) or {}
        objects = data.get("objects", [])
        cleaned = []
        for item in objects[: settings.self_learn_max_objects]:
            if isinstance(item, dict) and item.get("name"):
                cleaned.append({
                    "name": str(item.get("name", "")).strip(),
                    "use": str(item.get("use", "")).strip(),
                })
        return cleaned
    except Exception as exc:
        logging.error("Groq object discovery failed: %s", exc)
        return []


def rebuild_selflearn_index(max_rows: int = 200) -> None:
    rows = selflearn_latest(max_rows)
    built = []
    for ts_utc, image_path, objects_json in rows:
        try:
            objects = json.loads(objects_json)
        except Exception:
            objects = []
        if not image_path or not Path(image_path).exists() or not objects:
            continue
        hashed = average_hash_int(image_path)
        if hashed is None:
            continue
        built.append({"ts": ts_utc, "image": image_path, "objects": objects, "hash": int(hashed)})
    with selflearn_index_lock:
        selflearn_index.clear()
        selflearn_index.extend(built)


def selflearn_candidates_by_hash(query_hash: int, k: int) -> list[dict]:
    with selflearn_index_lock:
        data = list(selflearn_index)
    if not data:
        rebuild_selflearn_index()
        with selflearn_index_lock:
            data = list(selflearn_index)
    scored = [(hamming(query_hash, int(item["hash"])), item) for item in data]
    scored.sort(key=lambda pair: pair[0])
    return [item for _, item in scored[: max(1, k)]]


def groq_pick_object_from_selflearn(query_path: str | Path, candidates: list[dict]) -> str | None:
    client = get_groq_client()
    settings = get_settings()
    if client is None or not candidates:
        return None
    names: list[str] = []
    for candidate in candidates:
        for obj in candidate.get("objects", []):
            name = (obj.get("name") or "").strip()
            if name and name.lower() not in [item.lower() for item in names]:
                names.append(name)
    if not names:
        return None
    try:
        content = [
            {
                "type": "text",
                "text": (
                    "Choose exactly one object name from the candidate list if it is visible in the query image. "
                    "Otherwise reply unknown. Return only the name."
                ),
            },
            {"type": "text", "text": f"Candidate names: {', '.join(names)}"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image(query_path)}"}},
        ]
        for candidate in candidates[: settings.self_learn_match_max]:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image(candidate['image'])}"}})
        with groq_lock:
            response = client.chat.completions.create(
                messages=[{"role": "user", "content": content}],
                model=settings.groq_vision_model,
                temperature=0.0,
                max_tokens=30,
            )
        answer = (response.choices[0].message.content or "").strip().lower()
        if answer == "unknown":
            return "unknown"
        for name in names:
            if answer == name.lower() or name.lower() in answer:
                return name
        return "unknown"
    except Exception as exc:
        logging.error("Selflearn pick failed: %s", exc)
        return None


def run_self_discovery_once() -> None:
    image_path = capture_image_selflearn()
    if not image_path:
        return
    objects = groq_object_discovery(image_path)
    if not objects:
        return
    ts_utc = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    selflearn_add(ts_utc, str(image_path), objects)
    with selflearn_cache_lock:
        selflearn_cache["ts_utc"] = ts_utc
        selflearn_cache["objects"] = objects
    rebuild_selflearn_index()


def speak_what_i_learned() -> bool:
    with selflearn_cache_lock:
        objects = list(selflearn_cache.get("objects") or [])
    if not objects:
        rows = selflearn_latest(1)
        if rows:
            try:
                objects = json.loads(rows[0][2])
            except Exception:
                objects = []
    if not objects:
        play_tts_response("I have not self learned anything yet.")
        return True
    names = [obj.get("name", "").strip() for obj in objects if obj.get("name")]
    if not names:
        play_tts_response("I learned something, but I could not extract object names.")
        return True
    play_tts_response(f"I self learned these objects: {', '.join(names[:6])}.")
    return True


def pick_from_selflearn(query_path: str | Path) -> str | None:
    settings = get_settings()
    query_hash = average_hash_int(query_path)
    if query_hash is None:
        return None
    candidates = selflearn_candidates_by_hash(query_hash, settings.self_learn_match_max)
    if not candidates:
        return None
    distance = hamming(int(query_hash), int(candidates[0]["hash"]))
    if distance <= settings.self_learn_hash_strict:
        objects = candidates[0].get("objects") or []
        if objects:
            return (objects[0].get("name") or "").strip() or None
    if distance <= settings.self_learn_hash_loose:
        return groq_pick_object_from_selflearn(query_path, candidates)
    return None


def self_discovery_loop() -> None:
    settings = get_settings()
    next_run = None
    while True:
        try:
            if not settings.self_learn_enabled:
                time.sleep(5)
                continue
            is_active, sleep_since = get_robot_state()
            if is_active or not sleep_since:
                next_run = None
                time.sleep(1)
                continue
            now = time.time()
            if (now - sleep_since) < settings.self_learn_sleep_delay_sec:
                next_run = None
                time.sleep(1)
                continue
            if next_run is None:
                next_run = sleep_since + settings.self_learn_sleep_delay_sec
            if now >= next_run:
                run_self_discovery_once()
                next_run = now + settings.self_learn_interval_sec
            time.sleep(1)
        except Exception:
            logging.exception("self_discovery_loop error")
            time.sleep(5)
