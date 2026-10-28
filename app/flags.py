from __future__ import annotations

import hashlib
from pathlib import Path

import imagehash
from PIL import Image


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def flag_reasons(upload_path: Path, reference_path: Path, ssim_raw: float) -> str | None:
    reasons: list[str] = []
    if sha256_file(upload_path) == sha256_file(reference_path):
        reasons.append("exact copy")
    upload_hash = imagehash.phash(Image.open(upload_path))
    reference_hash = imagehash.phash(Image.open(reference_path))
    if (upload_hash - reference_hash) <= 8:
        reasons.append("near copy")
    if ssim_raw > 0.95:
        reasons.append("ssim")
    return ", ".join(reasons) if reasons else None
