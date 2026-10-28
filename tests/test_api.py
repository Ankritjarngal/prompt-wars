import io
import time

from PIL import Image

from app.flags import flag_reasons


def png(color, size=32) -> bytes:
    image = Image.new("RGB", (size, size), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def login_admin(client):
    response = client.post("/api/admin/login", json={"username": "admin", "password": "secret"})
    assert response.status_code == 200


def set_references(client):
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    for slot, color in enumerate(colors, start=1):
        response = client.post(
            f"/api/admin/rounds/1/references/{slot}",
            files={"file": (f"{slot}.png", png(color), "image/png")},
        )
        assert response.status_code == 200, response.text


def auth_player(client, code):
    response = client.post("/api/login", json={"code": code})
    assert response.status_code == 200, response.text


def wait_until(predicate, timeout=5):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.05)
    raise AssertionError(last)


def test_session_replacement_and_hidden_reference(client):
    login_admin(client)
    set_references(client)
    code = client.post("/api/admin/codes", json={"count": 1}).json()["codes"][0]
    assert client.post("/api/login", json={"code": code}).status_code == 200
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["screen"] == "waiting"
    state = client.get("/api/admin/state").json()
    ref_id = state["rounds"][0]["references"][0]["id"]
    admin_cookie = client.cookies.get("pw_admin")
    client.cookies.delete("pw_admin")
    hidden = client.get(f"/media/reference/{ref_id}")
    assert hidden.status_code == 403
    client.cookies.set("pw_admin", admin_cookie)
    first = client.cookies.get("pw_session")
    assert client.post("/api/login", json={"code": code}).status_code == 200
    client.cookies.set("pw_session", first)
    assert client.get("/api/me").status_code == 401


def test_two_slots_score_best_and_flag_identical_upload(client):
    login_admin(client)
    set_references(client)
    code = client.post("/api/admin/codes", json={"count": 1}).json()["codes"][0]
    client.post("/api/admin/rounds/1/settings", json={"duration_minutes": 40, "cut_size": 30, "notes": ""})
    assert client.post("/api/admin/rounds/1/activate").status_code == 200
    auth_player(client, code)
    me = client.get("/api/me").json()
    assert me["screen"] == "play"
    assert len(me["round"]["images"]) == 3
    ref = me["round"]["images"][0]
    reference = client.get(ref["url"])
    assert reference.status_code == 200
    copied = reference.content
    upload = client.post(
        "/api/uploads",
        data={"reference_slot": "1", "attempt": "1", "prompt": "copied"},
        files={"file": ("same.png", copied, "image/png")},
    )
    assert upload.status_code == 200, upload.text
    other = client.post(
        "/api/uploads",
        data={"reference_slot": "1", "attempt": "2", "prompt": ""},
        files={"file": ("other.png", png((10, 10, 10)), "image/png")},
    )
    assert other.status_code == 200
    locked = client.post(
        "/api/uploads",
        data={"reference_slot": "1", "attempt": "1"},
        files={"file": ("again.png", png((1, 2, 3)), "image/png")},
    )
    assert locked.status_code == 409

    def scored():
        body = client.get("/api/me").json()
        attempts = body["round"]["images"][0]["attempts"]
        if all(item["status"] == "scored" for item in attempts):
            return body
        return None

    body = wait_until(scored)
    image = body["round"]["images"][0]
    assert "flag" not in image["attempts"][0]
    assert image["counting_attempt"] == 1
    assert image["counting_score"] == 100
    state = client.get("/api/admin/state").json()
    flagged = state["rounds"][0]["leaderboard"][0]["submissions"]
    exact = next(row for row in flagged if row["attempt"] == 1)
    assert "exact copy" in exact["flag_reason"]
    assert client.post(f"/api/admin/submissions/{exact['id']}/void").status_code == 200
    after = client.get("/api/me").json()["round"]["images"][0]
    assert after["counting_attempt"] == 2
    assert after["counting_score"] < 100


def test_late_upload_rejected_and_round_two_cannot_activate(client):
    login_admin(client)
    set_references(client)
    code = client.post("/api/admin/codes", json={"count": 1}).json()["codes"][0]
    assert client.post("/api/admin/rounds/2/activate").status_code == 400
    assert client.post("/api/admin/rounds/1/activate").status_code == 200
    from app.db import connect, stamp, utcnow
    from datetime import timedelta

    past = stamp(utcnow() - timedelta(seconds=5))
    with connect(client.app.state.settings) as conn:
        conn.execute("UPDATE rounds SET ends_at = ? WHERE id = 1", (past,))
    auth_player(client, code)
    response = client.post(
        "/api/uploads",
        data={"reference_slot": "1", "attempt": "1"},
        files={"file": ("x.png", png((9, 9, 9)), "image/png")},
    )
    assert response.status_code == 400
    assert client.get("/api/me").json()["screen"] == "standby"


def test_custom_cut_extend_restart_and_manual_advancement(client):
    login_admin(client)
    set_references(client)
    codes = client.post("/api/admin/codes", json={"count": 4}).json()["codes"]
    assert client.post(
        "/api/admin/rounds/1/settings",
        json={"duration_minutes": 15, "cut_size": 1, "notes": "room of 4"},
    ).status_code == 200
    assert client.post("/api/admin/rounds/1/activate").status_code == 200
    started = client.get("/api/admin/state").json()["rounds"][0]["ends_at"]
    assert client.post("/api/admin/rounds/1/extend", json={"minutes": 10}).status_code == 200
    extended = client.get("/api/admin/state").json()["rounds"][0]["ends_at"]
    assert extended > started
    colors = [(20, 20, 20), (40, 40, 40), (80, 80, 80), (120, 120, 120)]
    for code, color in zip(codes, colors):
        auth_player(client, code)
        response = client.post(
            "/api/uploads",
            data={"reference_slot": "1", "attempt": "1"},
            files={"file": ("p.png", png(color), "image/png")},
        )
        assert response.status_code == 200, response.text

    def finished():
        board = client.get("/api/admin/state").json()["rounds"][0]["leaderboard"]
        scored = [row for row in board if any(sub["status"] == "scored" for sub in row["submissions"])]
        return board if len(scored) == 4 else None

    board = wait_until(finished)
    assert client.post("/api/admin/rounds/1/end").status_code == 200
    state = client.get("/api/admin/state").json()["rounds"][0]
    checked = [row["code"] for row in state["advancement"] if row["included"]]
    assert checked == [board[0]["code"]]
    assert client.post("/api/admin/rounds/1/settings", json={
        "duration_minutes": 15, "cut_size": 2, "notes": "room of 4"
    }).status_code == 200
    assert client.post("/api/admin/rounds/1/suggest").status_code == 200
    state = client.get("/api/admin/state").json()["rounds"][0]
    checked = [row for row in state["advancement"] if row["included"]]
    assert len(checked) == 2
    bottom = [row["participant_id"] for row in state["advancement"] if not row["included"]]
    assert client.put(
        "/api/admin/rounds/1/advancement",
        json={"participant_ids": bottom},
    ).status_code == 200
    assert client.post("/api/admin/rounds/1/advancement/confirm").status_code == 200
    auth_player(client, bottom and state["advancement"][-1]["code"])
    # The saved selection is the previously unchecked people. Confirm, then the last code advanced.
    last_code = state["advancement"][-1]["code"]
    auth_player(client, last_code)
    assert client.get("/api/me").json()["screen"] == "advanced"
    top_code = state["advancement"][0]["code"]
    auth_player(client, top_code)
    assert client.get("/api/me").json()["screen"] == "out"
    assert client.post("/api/admin/rounds/1/extend", json={"minutes": 5}).status_code == 200
    reopened = client.get("/api/admin/state").json()["rounds"][0]
    assert reopened["status"] == "live"
    assert reopened["advancement_confirmed"] is False
    assert client.post("/api/admin/rounds/1/restart", json={"confirm": "nope"}).status_code == 400
    assert client.post("/api/admin/rounds/1/restart", json={"confirm": "RESTART"}).status_code == 200
    restarted = client.get("/api/admin/state").json()["rounds"][0]
    assert restarted["status"] == "draft"
    assert len(restarted["references"]) == 3
    assert restarted["leaderboard"][0]["submissions"] == []
    assert len(client.get("/api/admin/state").json()["codes"]) == 4
    blocked = client.post(
        "/api/admin/rounds/1/references/1",
        files={"file": ("n.png", png((1, 1, 1)), "image/png")},
    )
    assert blocked.status_code == 200


def test_image_replace_locks_while_live(client):
    login_admin(client)
    set_references(client)
    client.post("/api/admin/codes", json={"count": 1})
    client.post("/api/admin/rounds/1/activate")
    response = client.post(
        "/api/admin/rounds/1/references/1",
        files={"file": ("n.png", png((3, 3, 3)), "image/png")},
    )
    assert response.status_code == 400


def test_flag_sees_a_reencoded_copy():
    import tempfile
    from pathlib import Path

    image = Image.new("RGB", (64, 64), (180, 20, 20))
    original = io.BytesIO()
    image.save(original, format="PNG")
    jpeg = io.BytesIO()
    image.save(jpeg, format="JPEG")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        left = root / "a.png"
        right = root / "b.jpg"
        left.write_bytes(original.getvalue())
        right.write_bytes(jpeg.getvalue())
        reasons = flag_reasons(right, left, 0.2)
    assert reasons is not None
    assert "exact copy" not in reasons
    assert "near copy" in reasons
