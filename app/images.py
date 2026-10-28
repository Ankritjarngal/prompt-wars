from __future__ import annotations

import hashlib
import io

from PIL import Image

from app.db import AppError


def inspect_image(data: bytes, limit: int) -> tuple[str, str]:
    if not data:
        raise AppError("Choose an image file")
    if len(data) > limit:
        raise AppError("That file is over the upload limit")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise AppError("That file is not a readable PNG or JPG") from exc
    if image.format not in ("PNG", "JPEG"):
        raise AppError("PNG or JPG only")
    if image.width > 8000 or image.height > 8000:
        raise AppError("Image is too large")
    media = "image/png" if image.format == "PNG" else "image/jpeg"
    digest = hashlib.sha256(data).hexdigest()
    return media, digest
