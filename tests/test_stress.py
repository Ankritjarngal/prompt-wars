import io
import threading
import time

import httpx
import uvicorn
from PIL import Image

from app.main import app


def png(color) -> bytes:
    image = Image.new("RGB", (16, 16), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def login_admin(client):
    assert client.post("/api/admin/login", json={"username": "admin", "password": "secret"}).status_code == 200


def set_references(client):
    for slot, color in enumerate([(255, 0, 0), (0, 180, 0), (0, 0, 255)], start=1):
        response = client.post(
            f"/api/admin/rounds/1/references/{slot}",
            files={"file": (f"{slot}.png", png(color), "image/png")},
        )
        assert response.status_code == 200, response.text


def test_cutoff_is_custom_for_sixty_people(client):
    login_admin(client)
    set_references(client)
    codes = client.post("/api/admin/codes", json={"count": 60}).json()["codes"]
    assert len(codes) == 60
    assert client.post(
        "/api/admin/rounds/1/settings",
        json={"duration_minutes": 40, "cut_size": 30, "notes": "60 in the room"},
    ).status_code == 200
    assert client.post("/api/admin/rounds/1/activate").status_code == 200
    for index, code in enumerate(codes):
        assert client.post("/api/login", json={"code": code}).status_code == 200
        color = ((index * 3) % 256, (index * 5) % 256, (index * 7) % 256)
        response = client.post(
            "/api/uploads",
            data={"reference_slot": "1", "attempt": "1"},
            files={"file": ("p.png", png(color), "image/png")},
        )
        assert response.status_code == 200, response.text

    deadline = time.time() + 30
    board = None
    while time.time() < deadline:
        board = client.get("/api/admin/state").json()["rounds"][0]["leaderboard"]
        scored = sum(1 for row in board if any(sub["status"] == "scored" for sub in row["submissions"]))
        if scored == 60:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("timed out waiting for 60 scores")

    assert client.post("/api/admin/rounds/1/end").status_code == 200
    state = client.get("/api/admin/state").json()["rounds"][0]
    checked = [row["code"] for row in state["advancement"] if row["included"]]
    assert len(checked) == 30
    assert checked == [row["code"] for row in board[:30]]

    assert client.post(
        "/api/admin/rounds/1/settings",
        json={"duration_minutes": 40, "cut_size": 37, "notes": "pull more people"},
    ).status_code == 200
    assert client.post("/api/admin/rounds/1/suggest").status_code == 200
    state = client.get("/api/admin/state").json()["rounds"][0]
    checked = [row["code"] for row in state["advancement"] if row["included"]]
    assert len(checked) == 37
    assert checked == [row["code"] for row in state["leaderboard"][:37]]


class _Server(uvicorn.Server):
    def install_signal_handlers(self):
        return


def test_sixty_parallel_uploads(client):
    login_admin(client)
    set_references(client)
    codes = client.post("/api/admin/codes", json={"count": 60}).json()["codes"]
    assert client.post("/api/admin/rounds/1/activate").status_code == 200
    port = 8877
    server = _Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=0.2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        raise AssertionError("server did not start")

    errors = []

    def attempt(index: int, code: str) -> None:
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as http:
                login = http.post("/api/login", json={"code": code})
                if login.status_code != 200:
                    errors.append(login.text)
                    return
                color = ((index * 3) % 256, 10, 10)
                upload = http.post(
                    "/api/uploads",
                    data={"reference_slot": "2", "attempt": "1"},
                    files={"file": ("p.png", png(color), "image/png")},
                )
                if upload.status_code != 200:
                    errors.append(upload.text)
        except Exception as exc:
            errors.append(str(exc))

    workers = [threading.Thread(target=attempt, args=(index, code)) for index, code in enumerate(codes)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
    server.should_exit = True
    thread.join(timeout=5)
    assert errors == []
    deadline = time.time() + 30
    while time.time() < deadline:
        board = client.get("/api/admin/state").json()["rounds"][0]["leaderboard"]
        scored = sum(
            1
            for row in board
            if any(sub["image_slot"] == 2 and sub["status"] == "scored" for sub in row["submissions"])
        )
        if scored == 60:
            return
        time.sleep(0.05)
    raise AssertionError("parallel uploads did not all score")
