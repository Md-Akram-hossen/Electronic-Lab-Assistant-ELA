from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

import numpy as np
from PIL import Image

from .audio import play_tts_response
from .camera import capture_image, encode_image
from .config import get_groq_client, get_settings
from .motion import vision_servo_scan
from .state import groq_lock

try:
    import face_recognition
except Exception:
    face_recognition = None

try:
    import cv2
except Exception:
    cv2 = None

faces_lock = Lock()
objects_lock = Lock()

face_encodings: list[np.ndarray] = []
face_labels: list[str] = []
face_hashes: list[int] = []
face_img_paths: list[str] = []
face_img_labels: list[str] = []

object_descs: list[np.ndarray] = []
object_labels: list[str] = []
object_hashes: list[int] = []
object_img_paths: list[str] = []
object_img_labels: list[str] = []

HASH_SIZE = 16
GROQ_MATCH_MAX = 3


def bitcount(value: int) -> int:
    return int(value).bit_count()


def hamming(a: int, b: int) -> int:
    return bitcount(a ^ b)


def average_hash_int(image_path: str | Path, hash_size: int = HASH_SIZE) -> int | None:
    try:
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        image = image.crop((left, top, left + side, top + side)).convert("L").resize((hash_size, hash_size), Image.LANCZOS)
        arr = np.asarray(image, dtype=np.float32)
        avg = float(arr.mean())
        bits = (arr > avg).astype(np.uint8).flatten()
        out = 0
        for bit in bits:
            out = (out << 1) | int(bit)
        return out
    except Exception:
        return None


def label_from_filename(path: str | Path) -> str:
    stem = Path(path).stem
    return stem.rsplit("_", 1)[0].strip() if "_" in stem else stem.strip()


def init_storage_dirs() -> None:
    settings = get_settings()
    settings.faces_dir.mkdir(parents=True, exist_ok=True)
    settings.objects_dir.mkdir(parents=True, exist_ok=True)


def load_faces_index() -> None:
    settings = get_settings()
    with faces_lock:
        face_encodings.clear()
        face_labels.clear()
        face_hashes.clear()
        face_img_paths.clear()
        face_img_labels.clear()
        for file in settings.faces_dir.iterdir():
            if file.suffix == ".npy":
                try:
                    face_encodings.append(np.load(file))
                    face_labels.append(file.stem.rsplit("_", 1)[0])
                except Exception:
                    continue
            elif file.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                hashed = average_hash_int(file)
                if hashed is not None:
                    face_hashes.append(hashed)
                    face_img_paths.append(str(file))
                    face_img_labels.append(label_from_filename(file))


def load_objects_index() -> None:
    settings = get_settings()
    with objects_lock:
        object_descs.clear()
        object_labels.clear()
        object_hashes.clear()
        object_img_paths.clear()
        object_img_labels.clear()
        for file in settings.objects_dir.iterdir():
            if file.suffix == ".npz":
                try:
                    data = np.load(file)
                    object_descs.append(data["desc"])
                    object_labels.append(str(data["label"]))
                except Exception:
                    continue
            elif file.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                hashed = average_hash_int(file)
                if hashed is not None:
                    object_hashes.append(hashed)
                    object_img_paths.append(str(file))
                    object_img_labels.append(label_from_filename(file))


def init_learning_indexes() -> None:
    init_storage_dirs()
    load_faces_index()
    load_objects_index()


def _orb_extract(image_path: str | Path):
    if cv2 is None:
        return None
    try:
        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            return None
        orb = cv2.ORB_create(nfeatures=1500)
        _, desc = orb.detectAndCompute(image, None)
        return desc
    except Exception:
        return None


def _top_k_by_hash(query_hash: int, labels: list[str], paths: list[str], hashes: list[int], k: int) -> list[tuple[str, str]]:
    best_per_label: dict[str, tuple[int, str]] = {}
    for label, path, hashed in zip(labels, paths, hashes):
        distance = hamming(query_hash, int(hashed))
        if label not in best_per_label or distance < best_per_label[label][0]:
            best_per_label[label] = (distance, path)
    ranked = sorted(best_per_label.items(), key=lambda item: item[1][0])
    return [(label, path) for label, (_, path) in ranked[: max(1, k)]]


def _groq_pick_best_label(kind: str, query_path: str | Path, candidates: list[tuple[str, str]]) -> str | None:
    client = get_groq_client()
    settings = get_settings()
    if not client or not candidates:
        return None
    try:
        content = [{
            "type": "text",
            "text": f"Identify the {kind} in the query image. Choose exactly one candidate label or reply unknown.",
        }]
        content.append({"type": "text", "text": "QUERY:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image(query_path)}"}})
        for index, (label, path) in enumerate(candidates, start=1):
            content.append({"type": "text", "text": f"Candidate {index}: {label}"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image(path)}"}})
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
        for label, _ in candidates:
            if answer == label.lower() or label.lower() in answer:
                return label
        return "unknown"
    except Exception as exc:
        logging.error("Groq label selection failed: %s", exc)
        return None


def learn_face(name: str) -> bool:
    clean_name = "".join(ch for ch in name if ch.isalnum() or ch in {" ", "_", "-"}).strip()
    if not clean_name:
        play_tts_response("Please provide a valid name.")
        return False
    image_path = capture_image()
    if not image_path:
        play_tts_response("Could not capture image.")
        return False
    settings = get_settings()
    if face_recognition is not None:
        try:
            image = face_recognition.load_image_file(str(image_path))
            boxes = face_recognition.face_locations(image, model="hog")
            if boxes:
                encodings = face_recognition.face_encodings(image, known_face_locations=boxes)
                if encodings:
                    np.save(settings.faces_dir / f"{clean_name}_{uuid4().hex}.npy", encodings[0])
        except Exception:
            pass
    try:
        Image.open(image_path).convert("RGB").save(settings.faces_dir / f"{clean_name}_{uuid4().hex}.jpg", "JPEG", quality=92)
        load_faces_index()
        play_tts_response(f"Learned face for {clean_name}.")
        return True
    except Exception as exc:
        logging.error("Learn face error: %s", exc)
        play_tts_response("Learning face failed.")
        return False


def recognize_face():
    settings = get_settings()
    image_path = capture_image()
    if not image_path:
        play_tts_response("Could not capture image.")
        return None
    if face_recognition is not None and face_encodings:
        try:
            image = face_recognition.load_image_file(str(image_path))
            boxes = face_recognition.face_locations(image, model="hog")
            encodings = face_recognition.face_encodings(image, known_face_locations=boxes)
            if encodings:
                distances = face_recognition.face_distance(face_encodings, encodings[0])
                index = int(np.argmin(distances))
                if float(distances[index]) <= settings.face_match_threshold:
                    label = face_labels[index]
                    play_tts_response(f"This is {label}.")
                    return label
        except Exception:
            pass
    if not face_img_paths:
        play_tts_response("I haven't learned any faces yet.")
        return None
    query_hash = average_hash_int(image_path)
    if query_hash is None:
        play_tts_response("I couldn't process the image.")
        return None
    candidates = _top_k_by_hash(query_hash, face_img_labels, face_img_paths, face_hashes, GROQ_MATCH_MAX)
    if not candidates:
        play_tts_response("I don't recognize this person.")
        return "unknown"
    best_label, best_path = candidates[0]
    best_hash = average_hash_int(best_path)
    best_distance = hamming(query_hash, best_hash) if best_hash is not None else 999
    if best_distance <= settings.face_hash_strict:
        play_tts_response(f"This is {best_label}.")
        return best_label
    if best_distance <= settings.face_hash_loose:
        chosen = _groq_pick_best_label("person", image_path, candidates)
        if chosen and chosen != "unknown":
            play_tts_response(f"This is {chosen}.")
            return chosen
    play_tts_response("I don't recognize this person.")
    return "unknown"


def learn_object(label: str) -> bool:
    clean_label = "".join(ch for ch in label if ch.isalnum() or ch in {" ", "_", "-"}).strip()
    if not clean_label:
        play_tts_response("Please provide a valid object name.")
        return False
    image_path = capture_image()
    if not image_path:
        play_tts_response("Could not capture image.")
        return False
    settings = get_settings()
    if cv2 is not None:
        desc = _orb_extract(image_path)
        if desc is not None and len(desc) > 0:
            np.savez_compressed(settings.objects_dir / f"{clean_label}_{uuid4().hex}.npz", desc=desc, label=clean_label)
    try:
        Image.open(image_path).convert("RGB").save(settings.objects_dir / f"{clean_label}_{uuid4().hex}.jpg", "JPEG", quality=92)
        load_objects_index()
        play_tts_response(f"Learned object {clean_label}.")
        return True
    except Exception as exc:
        logging.error("Learn object error: %s", exc)
        play_tts_response("Learning object failed.")
        return False


def recognize_object():
    settings = get_settings()
    image_path = capture_image()
    if not image_path:
        play_tts_response("Could not capture image.")
        return None
    if cv2 is not None and object_descs:
        query_desc = _orb_extract(image_path)
        if query_desc is not None and len(query_desc) > 0:
            try:
                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
                best_label = None
                best_good = -1
                for candidate_desc, label in zip(object_descs, object_labels):
                    matches = bf.knnMatch(query_desc, candidate_desc, k=2)
                    good = sum(1 for m, n in matches if m.distance < 0.75 * n.distance)
                    if good > best_good:
                        best_good = good
                        best_label = label
                if best_label and best_good >= settings.object_min_good_matches:
                    play_tts_response(f"This is {best_label}.")
                    return best_label
            except Exception:
                pass
    if object_img_paths:
        query_hash = average_hash_int(image_path)
        if query_hash is not None:
            candidates = _top_k_by_hash(query_hash, object_img_labels, object_img_paths, object_hashes, GROQ_MATCH_MAX)
            if candidates:
                best_label, best_path = candidates[0]
                best_hash = average_hash_int(best_path)
                best_distance = hamming(query_hash, best_hash) if best_hash is not None else 999
                if best_distance <= settings.object_hash_strict:
                    play_tts_response(f"This is {best_label}.")
                    return best_label
                if best_distance <= settings.object_hash_loose:
                    chosen = _groq_pick_best_label("object", image_path, candidates)
                    if chosen and chosen != "unknown":
                        play_tts_response(f"This is {chosen}.")
                        return chosen
    from .self_learning import pick_from_selflearn
    picked = pick_from_selflearn(image_path)
    if picked and picked != "unknown":
        play_tts_response(f"This is {picked}.")
        return picked
    play_tts_response("I did not learn this yet.")
    return "unknown"


def describe_scene() -> str:
    client = get_groq_client()
    settings = get_settings()
    vision_servo_scan()
    image_path = capture_image()
    if not image_path:
        return "I'm sorry, I couldn't capture the image."
    if client is None:
        return "Vision model is not configured."
    try:
        with groq_lock:
            response = client.chat.completions.create(
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Give me a short answer about what you see in this image."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image(image_path)}"}},
                    ],
                }],
                model=settings.groq_vision_model,
                temperature=0.0,
                max_tokens=120,
            )
        text = (response.choices[0].message.content or "").strip()
        return f"I see {text[0].lower() + text[1:]}" if text else "I see something, but I couldn't describe it."
    except Exception as exc:
        logging.error("Vision description failed: %s", exc)
        return "I'm sorry, I couldn't analyze the image."
