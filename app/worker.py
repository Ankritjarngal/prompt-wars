from __future__ import annotations

import logging
import queue
import threading

from app.config import Settings
from app.db import complete_submission, fail_submission, queued_submission
from app.flags import flag_reasons
from app.scoring import RawMetrics, combine

log = logging.getLogger("prompt_wars")


class ScoreWorker:
    def __init__(self, settings: Settings, scorer):
        self.settings = settings
        self.scorer = scorer
        self.queue: queue.Queue[int | None] = queue.Queue()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="score-worker", daemon=True)
        self.thread.start()

    def submit(self, submission_id: int) -> None:
        self.queue.put(submission_id)

    def stop(self) -> None:
        self.queue.put(None)
        if self.thread:
            self.thread.join(timeout=5)

    def _run(self) -> None:
        while True:
            submission_id = self.queue.get()
            if submission_id is None:
                return
            try:
                self._score_one(submission_id)
            except Exception:
                log.exception("score failed for %s", submission_id)
                fail_submission(self.settings, submission_id, "Scoring failed. Submit this slot again.")

    def _score_one(self, submission_id: int) -> None:
        row = queued_submission(self.settings, submission_id)
        if not row or row["status"] != "queued":
            return
        upload = self.settings.data_dir / row["stored_path"]
        reference = self.settings.data_dir / row["reference_path"]
        raw = self.scorer.raw_pair(upload, reference)
        if row["lpips_floor"] is None:
            from app.db import ensure_calibration

            reference_row = {
                "id": row["reference_id"],
                "stored_path": row["reference_path"],
            }
            ensure_calibration(self.settings, self.scorer, reference_row)
            row = queued_submission(self.settings, submission_id)
            if not row:
                return
        floor = RawMetrics(row["lpips_floor"], row["ssim_floor"], row["dino_floor"])
        ceiling = RawMetrics(row["lpips_ceiling"], row["ssim_ceiling"], row["dino_ceiling"])
        lpips_score, ssim_score, dino_score, total = combine(raw, floor, ceiling)
        reason = flag_reasons(upload, reference, raw.ssim)
        complete_submission(
            self.settings,
            submission_id,
            {
                "lpips_raw": raw.lpips,
                "ssim_raw": raw.ssim,
                "dino_raw": raw.dino,
                "lpips_score": lpips_score,
                "ssim_score": ssim_score,
                "dino_score": dino_score,
                "total_score": total,
                "flag_reason": reason,
            },
        )
