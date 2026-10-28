from io import BytesIO

from PIL import Image, ImageDraw

from app.config import Settings
from app.db import init_db, save_reference
from app.images import inspect_image
from app.scoring import build_scorer


def _png(color: tuple[int, int, int], label: str) -> bytes:
    image = Image.new("RGB", (320, 320), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 280, 280), outline=(255, 255, 255), width=12)
    draw.text((120, 150), label, fill=(0, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> None:
    settings = Settings.from_env()
    init_db(settings)
    scorer = build_scorer(settings)
    scorer.load()
    colors = [((220, 40, 40), "ONE"), ((40, 160, 70), "TWO"), ((40, 80, 200), "THREE")]
    for slot, (color, label) in enumerate(colors, start=1):
        data = _png(color, label)
        media, digest = inspect_image(data, settings.max_upload_bytes)
        try:
            save_reference(settings, scorer, 1, slot, data, media, digest)
        except Exception as exc:
            print(f"Slot {slot} skipped: {exc}")
    print("Dev references are in data/references if those slots were empty or the round is still draft.")


if __name__ == "__main__":
    main()
