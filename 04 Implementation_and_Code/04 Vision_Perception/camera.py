from __future__ import annotations

import base64
import logging
import subprocess
from pathlib import Path

from .config import get_settings
from .state import camera_lock


def encode_image(path: str | Path) -> str:
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("utf-8")


def capture_image(filename: str = "image.jpg") -> Path | None:
    settings = get_settings()
    image_path = settings.base_dir / filename
    try:
        with camera_lock:
            subprocess.run(
                [
                    "rpicam-still",
                    "-o", str(image_path),
                    "--nopreview",
                    "--quality", "90",
                    "--shutter", "10000",
                    "--denoise", "cdn_off",
                ],
                check=True,
            )
        return image_path if image_path.exists() else None
    except Exception as exc:
        logging.error("Image capture error: %s", exc)
        return None


def capture_image_to(path: Path) -> Path | None:
    try:
        with camera_lock:
            subprocess.run(
                [
                    "rpicam-still",
                    "-o", str(path),
                    "--nopreview",
                    "--quality", "90",
                    "--shutter", "10000",
                    "--denoise", "cdn_off",
                ],
                check=True,
            )
        return path if path.exists() else None
    except Exception as exc:
        logging.error("Image capture error: %s", exc)
        return None
