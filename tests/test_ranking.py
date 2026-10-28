import pytest

from app.ranking import rank_participants
from app.scoring import RawMetrics, combine, scale


def _person(pid, code):
    return {"id": pid, "code": code}


def _sub(pid, reference_id, slot, total, lpips, at, voided=0):
    return {
        "id": pid * 10 + slot,
        "participant_id": pid,
        "reference_id": reference_id,
        "slot": slot,
        "status": "scored",
        "voided": voided,
        "total_score": total,
        "lpips_raw": lpips,
        "submitted_at": at,
    }


def test_best_of_two_sums_three_images_and_skips_voids():
    people = [_person(1, "AAAA")]
    subs = [
        _sub(1, 10, 1, 40, 0.4, "2026-01-01T00:00:00+00:00"),
        _sub(1, 10, 2, 70, 0.7, "2026-01-01T00:01:00+00:00"),
        _sub(1, 11, 1, 90, 0.9, "2026-01-01T00:02:00+00:00", voided=1),
        _sub(1, 11, 2, 10, 0.1, "2026-01-01T00:03:00+00:00"),
    ]
    ranked = rank_participants(people, subs, [10, 11, 12])
    assert ranked[0]["total"] == 80
    assert ranked[0]["lpips_sum"] == pytest.approx(0.8)
    assert ranked[0]["achieved_at"] == "2026-01-01T00:03:00+00:00"


def test_tie_on_an_image_keeps_the_earlier_upload():
    people = [_person(1, "AAAA")]
    subs = [
        _sub(1, 10, 1, 50, 0.2, "2026-01-01T00:00:00+00:00"),
        _sub(1, 10, 2, 50, 0.9, "2026-01-01T00:05:00+00:00"),
    ]
    ranked = rank_participants(people, subs, [10])
    assert ranked[0]["images"][0]["counting_slot"] == 1
    assert ranked[0]["lpips_sum"] == 0.2


def test_rank_order_uses_total_then_lpips_then_time_then_code():
    people = [_person(1, "BBBB"), _person(2, "AAAA"), _person(3, "CCCC"), _person(4, "DDDD")]
    subs = [
        _sub(1, 10, 1, 50, 0.4, "2026-01-01T00:02:00+00:00"),
        _sub(2, 10, 1, 50, 0.4, "2026-01-01T00:01:00+00:00"),
        _sub(3, 10, 1, 50, 0.9, "2026-01-01T00:09:00+00:00"),
        _sub(4, 10, 1, 10, 0.1, "2026-01-01T00:00:00+00:00"),
    ]
    ranked = rank_participants(people, subs, [10])
    assert [row["code"] for row in ranked] == ["CCCC", "AAAA", "BBBB", "DDDD"]


def test_scale_clamps_between_floor_and_ceiling():
    assert scale(1, 0, 1) == 100
    assert scale(0, 0, 1) == 0
    assert scale(2, 0, 1) == 100
    assert scale(5, 5, 5) == 100
    total = combine(RawMetrics(1, 1, 1), RawMetrics(0, 0, 0), RawMetrics(1, 1, 1))
    assert total[3] == 100
