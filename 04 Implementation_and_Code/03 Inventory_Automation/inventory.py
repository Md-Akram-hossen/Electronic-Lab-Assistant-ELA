from __future__ import annotations

from .audio import get_audio_input, play_tts_response
from .config import get_settings
from .google_client import send_email_with_attachment, send_simple_email
from .inventory_db import (
    add_borrow_txn,
    apply_return_fifo,
    atomic_borrow,
    atomic_return,
    export_components_excel,
    get_component,
    get_student,
    list_all_components,
    log_borrow,
    log_return,
    resolve_component_name,
)
from .iot import open_locker
from .otp import generate_and_send_otp, verify_spoken_otp
from .parsing import parse_component_quantity, parse_id_digits


def availability_response(name: str, qty: int, location: str) -> str:
    return (
        f"Oh, {name}, we have total {qty} {name} at this moment in our lab "
        f"which is available at {location}. If you want to borrow just tell me: I want to get {name}."
    )


def prompt_student_identity_and_quantity(item_name: str):
    play_tts_response("Tell me your student I D. Speak only digits.")
    student_id_text = get_audio_input()
    student_id = parse_id_digits(student_id_text or "")
    if not student_id:
        return None, None, None, "no-id"
    student = get_student(student_id)
    if not student:
        return None, None, None, "unknown-id"
    sid, student_name, student_email = student
    for attempt in range(2):
        play_tts_response(f"Hi {student_name}. How many {item_name}?")
        quantity_text = get_audio_input()
        quantity = parse_component_quantity(quantity_text or "")
        if quantity and quantity > 0:
            break
    else:
        return None, None, None, "bad-qty"
    play_tts_response("I will send a four digit verification code to your registered email.")
    if not generate_and_send_otp(sid, student_name, student_email):
        return None, None, None, "otp-send-failed"
    if not verify_spoken_otp(sid):
        return None, None, None, "otp-mismatch"
    return sid, student_name, quantity, None


def handle_borrow_component_flow(component_name: str) -> bool:
    row = get_component(component_name)
    if not row:
        play_tts_response(f"{component_name} is not in the inventory.")
        return True
    name, available_qty, location, locker = row
    sid, student_name, want_qty, error = prompt_student_identity_and_quantity(name)
    if error:
        play_tts_response({
            "no-id": "I did not catch a numeric ID. Access denied.",
            "unknown-id": "ID not recognized. Access denied.",
            "bad-qty": "Invalid quantity.",
            "otp-send-failed": "Verification code could not be sent. Access denied.",
            "otp-mismatch": "Verification failed. Access denied.",
        }[error])
        return True
    student = get_student(str(sid))
    student_email = (student[2] if student and len(student) >= 3 else "") or ""
    ok, remaining, info = atomic_borrow(name, want_qty)
    if not ok:
        if info == "insufficient-stock":
            play_tts_response(f"Only {available_qty} {name} available now.")
        elif info == "not-found":
            play_tts_response(f"{name} is not in the inventory.")
        else:
            play_tts_response("Inventory update failed.")
        return True
    open_locker(info["locker"])
    borrow_dt, due_dt = add_borrow_txn(sid, student_name, student_email, name, want_qty)
    log_borrow(sid, student_name, name, want_qty, remaining)
    attachments = []
    exported = export_components_excel()
    if exported:
        attachments.append((
            "components.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            exported,
        ))
    body = (
        f"Borrow record\n"
        f"- Student: {student_name} (ID {sid})\n"
        f"- Student email: {student_email}\n"
        f"- Item: {name}\n"
        f"- Quantity: {want_qty}\n"
        f"- Locker opened: {info['locker']} ({info['location']})\n"
        f"- Remaining stock: {remaining}\n"
        f"- Borrow time (UTC): {borrow_dt.isoformat(timespec='seconds')}\n"
        f"- Due time (UTC): {due_dt.isoformat(timespec='seconds')}\n"
    )
    settings = get_settings()
    send_email_with_attachment(settings.lab_email, f"Borrowed {want_qty}x {name} by {student_name} ({sid})", body, attachments)
    if student_email:
        send_simple_email(
            student_email,
            f"Lab Borrow Confirmation: {want_qty}x {name}",
            (
                f"Hello {student_name},\n\n"
                f"Component: {name}\n"
                f"Quantity: {want_qty}\n"
                f"Borrow date: {borrow_dt.isoformat(timespec='seconds')}\n"
                f"Due date: {due_dt.isoformat(timespec='seconds')}\n\n"
                f"Please return the component before the due date.\n\nELA"
            ),
        )
    play_tts_response(
        f"Access granted. Opening locker {info['locker']}. "
        f"{want_qty} {name} registered. Remaining stock {remaining}."
    )
    return True


def handle_return_component_flow(component_name: str) -> bool:
    row = get_component(component_name)
    if not row:
        play_tts_response(f"{component_name} is not in the inventory.")
        return True
    name, _, location, locker = row
    sid, student_name, return_qty, error = prompt_student_identity_and_quantity(name)
    if error:
        play_tts_response({
            "no-id": "I did not catch a numeric ID. Access denied.",
            "unknown-id": "ID not recognized. Access denied.",
            "bad-qty": "Invalid quantity.",
            "otp-send-failed": "Verification code could not be sent. Access denied.",
            "otp-mismatch": "Verification failed. Access denied.",
        }[error])
        return True
    student = get_student(str(sid))
    student_email = (student[2] if student and len(student) >= 3 else "") or ""
    ok, new_total, info = atomic_return(name, return_qty)
    if not ok:
        play_tts_response("Inventory update failed.")
        return True
    open_locker(info["locker"])
    applied, unmatched = apply_return_fifo(sid, name, return_qty)
    log_return(sid, student_name, name, return_qty, new_total)
    settings = get_settings()
    exported = export_components_excel()
    attachments = []
    if exported:
        attachments.append((
            "components.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            exported,
        ))
    send_email_with_attachment(
        settings.lab_email,
        f"Returned {return_qty}x {name} by {student_name} ({sid})",
        (
            f"Return record\n"
            f"- Student: {student_name} (ID {sid})\n"
            f"- Student email: {student_email}\n"
            f"- Item: {name}\n"
            f"- Quantity returned: {return_qty}\n"
            f"- Applied to tracked borrows: {applied}\n"
            f"- Unmatched: {unmatched}\n"
            f"- New total stock: {new_total}\n"
        ),
        attachments,
    )
    if student_email:
        send_simple_email(
            student_email,
            f"Lab Return Confirmation: {return_qty}x {name}",
            (
                f"Hello {student_name},\n\n"
                f"Component: {name}\n"
                f"Quantity returned: {return_qty}\n\n"
                f"Thank you.\n\nELA"
            ),
        )
    play_tts_response(
        f"Return registered. Opening locker {info['locker']}. "
        f"{return_qty} {name} added. New stock {new_total}."
    )
    return True


def speak_component_availability(component_name: str) -> bool:
    component = resolve_component_name(component_name)
    row = get_component(component)
    if not row:
        play_tts_response(f"I can't find {component} in inventory.")
        return True
    name, qty, location, _ = row
    play_tts_response(availability_response(name, qty, location))
    return True


def speak_component_list() -> bool:
    rows = list_all_components()
    if not rows:
        play_tts_response("No components in the inventory.")
        return True
    preview = ", ".join(f"{name} ({qty})" for name, qty, _, _ in rows[:6])
    play_tts_response(f"Components: {preview}.")
    return True
