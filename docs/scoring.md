# Scoring

Round 1 scores one upload against the reference for that slot's image. The three image scores are independent. The round total is their sum.

## Per image, out of 100

Both images are converted to RGB and resized with bicubic interpolation to 224×224 in memory. Stored files are not modified.

| Part | Weight | Raw value | After calibration |
| --- | --- | --- | --- |
| LPIPS Alex | 50% | Similarity `1 - distance`. Distance comes from the lpips package, inputs in `[-1, 1]`, CPU, fp32, eval mode. | Scaled to 0–100 |
| SSIM | 30% | `skimage.metrics.structural_similarity` on the uint8 RGB images, `channel_axis=-1`, `data_range=255`. | Scaled to 0–100 |
| DINOv2 ViT-S/14 | 20% | Cosine similarity of the CLS embedding. ImageNet mean and std. `torch.hub` model `dinov2_vits14`. | Scaled to 0–100 |

Image score = `0.50 * lpips + 0.30 * ssim + 0.20 * dino`, each already 0–100. Stored as SQLite reals. The UI shows one decimal place.

Scale function:

```text
if ceiling <= floor:
    100 if raw >= ceiling else 0
else:
    clamp((raw - floor) / (ceiling - floor) * 100, 0, 100)
```

Higher raw is better for all three metrics.

## Calibration

Stored per reference image.

- Ceiling: score the reference against itself.
- Floor: for each metric, the lower of (blank gray image vs reference) and (noise image vs reference).
- The noise image is 224×224 RGB from NumPy's legacy random generator seeded with 0. Do not change the seed without re-calibrating.
- Calibration is computed when an admin uploads a reference, and again at startup for any reference that is missing it.
- Replacing a reference deletes its old calibration and computes a new one.
- `scripts/calibrate.py` recomputes floors and ceilings and scores one pair twice to check that both runs match.

`SKIP_MODELS=1` uses a fake scorer. Identical bytes score 1, 1, 1. Different bytes score below that, stably, from the file hash. Tests use the fake. Event day must not set `SKIP_MODELS`.

## Which slot counts

For each reference, consider submissions with `status = scored` and `voided = 0`. The counting row is the highest `total_score`. If scores are equal, the earlier `submitted_at` counts. No such row means that image contributes 0.

Round score = sum of the three counting totals.

## Rank

Sort participants by:

1. Round score, descending.
2. Sum of `lpips_raw` on the counting rows, descending.
3. Latest `submitted_at` among the counting rows, ascending. Someone with no counting upload sorts after everyone who has one.
4. Entry code, ascending.

That order is the rank shown to the player and the order used by Suggest top N. There is no remaining tie.

## Copy flags

Compared with the reference for that image only.

| Flag | Rule |
| --- | --- |
| exact copy | SHA-256 of the upload equals SHA-256 of the stored reference |
| near copy | Perceptual hash Hamming distance ≤ 8 (`imagehash.phash`, hash size 8) |
| ssim | Raw SSIM > 0.95 |

All matching reasons are stored in one text field, comma-separated. The score is still stored and still counts. The player API omits the flag. The admin can void the row.

Void sets `voided = 1`. It does not delete the file. The other slot becomes the counting score if it is scored and not voided.

## Queue

One worker thread. The upload request saves the file, inserts `status = queued`, and returns. The player poll picks up `scored` or a freed slot with an error.

Models load once at process start when `SKIP_MODELS` is not set. Weights go under `data/models/` via `TORCH_HOME` and the torch hub directory. The first real run needs a network path to download LPIPS Alex weights and DINOv2. After that the laptop can score offline.

An upload whose `submitted_at` is before the deadline is scored even if the round ends while it is queued.
