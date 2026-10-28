"""Pure Round 1 totals and rank order. Routes and tests both use this."""

from __future__ import annotations


def counting_submission(submissions: list[dict], reference_id: int) -> dict | None:
    candidates = [
        row
        for row in submissions
        if row["reference_id"] == reference_id
        and row["status"] == "scored"
        and not row["voided"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (-float(row["total_score"]), row["submitted_at"]))
    return candidates[0]


def score_participant(participant: dict, submissions: list[dict], reference_ids: list[int]) -> dict:
    counting = []
    total = 0.0
    lpips_sum = 0.0
    times: list[str] = []
    per_image = []
    for reference_id in reference_ids:
        chosen = counting_submission(submissions, reference_id)
        image_score = float(chosen["total_score"]) if chosen else 0.0
        total += image_score
        if chosen:
            lpips_sum += float(chosen["lpips_raw"] or 0)
            times.append(chosen["submitted_at"])
        per_image.append(
            {
                "reference_id": reference_id,
                "counting_score": image_score,
                "counting_slot": chosen["slot"] if chosen else None,
                "submission_id": chosen["id"] if chosen else None,
            }
        )
    return {
        "participant_id": participant["id"],
        "code": participant["code"],
        "total": total,
        "lpips_sum": lpips_sum,
        "achieved_at": max(times) if times else None,
        "images": per_image,
    }


def rank_participants(participants: list[dict], submissions: list[dict], reference_ids: list[int]) -> list[dict]:
    by_participant: dict[int, list[dict]] = {}
    for row in submissions:
        by_participant.setdefault(row["participant_id"], []).append(row)
    ranked = [
        score_participant(participant, by_participant.get(participant["id"], []), reference_ids)
        for participant in participants
    ]
    ranked.sort(
        key=lambda row: (
            -row["total"],
            -row["lpips_sum"],
            row["achieved_at"] is None,
            row["achieved_at"] or "",
            row["code"],
        )
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked
