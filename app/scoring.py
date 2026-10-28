from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from app.config import Settings


@dataclass(frozen=True)
class RawMetrics:
    lpips: float
    ssim: float
    dino: float


def scale(raw: float, floor: float, ceiling: float) -> float:
    if ceiling <= floor:
        return 100.0 if raw >= ceiling else 0.0
    value = (raw - floor) / (ceiling - floor) * 100.0
    return max(0.0, min(100.0, value))


def combine(raw: RawMetrics, floor: RawMetrics, ceiling: RawMetrics) -> tuple[float, float, float, float]:
    lpips = scale(raw.lpips, floor.lpips, ceiling.lpips)
    ssim = scale(raw.ssim, floor.ssim, ceiling.ssim)
    dino = scale(raw.dino, floor.dino, ceiling.dino)
    total = 0.50 * lpips + 0.30 * ssim + 0.20 * dino
    return lpips, ssim, dino, total


def _similarity_from_bytes(upload: bytes, reference: bytes) -> RawMetrics:
    if upload == reference:
        return RawMetrics(1.0, 1.0, 1.0)
    uh = int.from_bytes(__import__("hashlib").sha256(upload).digest(), "big")
    rh = int.from_bytes(__import__("hashlib").sha256(reference).digest(), "big")
    distance = (uh ^ rh).bit_count() / 256
    sim = max(0.0, 1.0 - distance)
    return RawMetrics(sim, sim * 0.9, sim * 0.8)


class FakeScorer:
    """Stable stand-in so the game can be tested without PyTorch."""

    def load(self) -> None:
        return None

    def raw_pair(self, upload_path: Path, reference_path: Path) -> RawMetrics:
        return _similarity_from_bytes(upload_path.read_bytes(), reference_path.read_bytes())

    def calibration_bounds(self, reference_path: Path) -> tuple[RawMetrics, RawMetrics]:
        del reference_path
        return RawMetrics(0.0, 0.0, 0.0), RawMetrics(1.0, 1.0, 1.0)


class RealScorer:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self._ready = False

    def load(self) -> None:
        try:
            import torch
            import lpips
        except ImportError as exc:
            raise RuntimeError(
                "Scoring models are not installed. Install PyTorch CPU and requirements-scoring.txt, "
                "or set SKIP_MODELS=1 for a dry run."
            ) from exc
        self.models_dir.mkdir(parents=True, exist_ok=True)
        os.environ["TORCH_HOME"] = str(self.models_dir)
        torch.hub.set_dir(str(self.models_dir / "hub"))
        torch.set_grad_enabled(False)
        self.torch = torch
        self.lpips_fn = lpips.LPIPS(net="alex")
        self.lpips_fn.eval()
        self.dino = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14")
        self.dino.eval()
        self._ready = True

    def _open(self, path: Path) -> Image.Image:
        image = Image.open(path).convert("RGB")
        return image.resize((224, 224), Image.Resampling.BICUBIC)

    def _lpips(self, left: Image.Image, right: Image.Image) -> float:
        import torchvision.transforms as transforms

        to_tensor = transforms.ToTensor()

        def prep(image: Image.Image):
            return to_tensor(image).unsqueeze(0) * 2 - 1

        with self.torch.inference_mode():
            distance = self.lpips_fn(prep(left), prep(right))
        return float(1.0 - distance.item())

    def _ssim(self, left: Image.Image, right: Image.Image) -> float:
        from skimage.metrics import structural_similarity

        return float(
            structural_similarity(
                np.asarray(left, dtype=np.uint8),
                np.asarray(right, dtype=np.uint8),
                channel_axis=-1,
                data_range=255,
            )
        )

    def _dino(self, left: Image.Image, right: Image.Image) -> float:
        import torchvision.transforms as transforms

        transform = transforms.Compose(
            [
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ]
        )

        def embed(image: Image.Image):
            tensor = transform(image).unsqueeze(0)
            with self.torch.inference_mode():
                features = self.dino(tensor)
            return self.torch.nn.functional.normalize(features, dim=-1)

        left_features = embed(left)
        right_features = embed(right)
        return float((left_features * right_features).sum().item())

    def raw_pair(self, upload_path: Path, reference_path: Path) -> RawMetrics:
        if not self._ready:
            raise RuntimeError("Call load() before scoring.")
        left = self._open(upload_path)
        right = self._open(reference_path)
        return RawMetrics(self._lpips(left, right), self._ssim(left, right), self._dino(left, right))

    def calibration_bounds(self, reference_path: Path) -> tuple[RawMetrics, RawMetrics]:
        ceiling = self.raw_pair(reference_path, reference_path)
        blank_path = self.models_dir / "_blank.png"
        noise_path = self.models_dir / "_noise.png"
        Image.new("RGB", (224, 224), (128, 128, 128)).save(blank_path)
        rng = np.random.RandomState(0)
        noise = rng.randint(0, 256, (224, 224, 3), dtype=np.uint8)
        Image.fromarray(noise, mode="RGB").save(noise_path)
        blank = self.raw_pair(blank_path, reference_path)
        noisy = self.raw_pair(noise_path, reference_path)
        floor = RawMetrics(
            min(blank.lpips, noisy.lpips),
            min(blank.ssim, noisy.ssim),
            min(blank.dino, noisy.dino),
        )
        return floor, ceiling


def build_scorer(settings: Settings):
    if settings.skip_models:
        return FakeScorer()
    return RealScorer(settings.data_dir / "models")
