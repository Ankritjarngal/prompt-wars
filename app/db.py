from __future__ import annotations

import csv
import io
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.ranking import rank_participants

WRITE = threading.Lock()
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

ROUND_SEED = (
    (1, "image-wars", "Image Wars", 40 * 60, 30, 1),
    (2, "black-box", "Black Box Cipher", 50 * 60, 10, 0),
    (3, "precision", "Prompt to Precision", 20 * 60, 3, 0),
)


class AppError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat()


def parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


@contextmanager
def connect(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(settings: Settings) -> None:
    for name in ("uploads", "references", "round_files", "models"):
        (settings.data_dir / name).mkdir(parents=True, exist_ok=True)
    with connect(settings) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                session_token TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rounds (
                id INTEGER PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                duration_seconds INTEGER NOT NULL,
                cut_size INTEGER NOT NULL,
                playable INTEGER NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                ends_at TEXT,
                advancement_confirmed INTEGER NOT NULL DEFAULT 0,
                advancement_frozen INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS reference_images (
                id INTEGER PRIMARY KEY,
                round_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                media_type TEXT NOT NULL,
                UNIQUE(round_id, slot)
            );
            CREATE TABLE IF NOT EXISTS calibration (
                reference_id INTEGER PRIMARY KEY,
                lpips_floor REAL NOT NULL,
                lpips_ceiling REAL NOT NULL,
                ssim_floor REAL NOT NULL,
                ssim_ceiling REAL NOT NULL,
                dino_floor REAL NOT NULL,
                dino_ceiling REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY,
                participant_id INTEGER NOT NULL,
                round_id INTEGER NOT NULL,
                reference_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                media_type TEXT NOT NULL,
                prompt_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                error TEXT,
                lpips_raw REAL,
                ssim_raw REAL,
                dino_raw REAL,
                lpips_score REAL,
                ssim_score REAL,
                dino_score REAL,
                total_score REAL,
                flag_reason TEXT,
                voided INTEGER NOT NULL DEFAULT 0,
                submitted_at TEXT NOT NULL,
                scored_at TEXT,
                UNIQUE(participant_id, reference_id, slot)
            );
            CREATE TABLE IF NOT EXISTS slot_errors (
                participant_id INTEGER NOT NULL,
                reference_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                message TEXT NOT NULL,
                at TEXT NOT NULL,
                PRIMARY KEY (participant_id, reference_id, slot)
            );
            CREATE TABLE IF NOT EXISTS advancement (
                from_round_id INTEGER NOT NULL,
                participant_id INTEGER NOT NULL,
                included INTEGER NOT NULL,
                PRIMARY KEY (from_round_id, participant_id)
            );
            CREATE TABLE IF NOT EXISTS round_files (
                id INTEGER PRIMARY KEY,
                round_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                uploaded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY,
                at TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT NOT NULL
            );
            """
        )
        existing = conn.execute("SELECT COUNT(*) AS n FROM rounds").fetchone()["n"]
        if existing == 0:
            conn.executemany(
                """
                INSERT INTO rounds (id, slug, name, duration_seconds, cut_size, playable)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ROUND_SEED,
            )


def wipe(settings: Settings) -> None:
    init_db(settings)
    with WRITE:
        with connect(settings) as conn:
            for table in (
                "slot_errors",
                "submissions",
                "calibration",
                "reference_images",
                "advancement",
                "round_files",
                "admin_actions",
                "admin_sessions",
                "participants",
                "rounds",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.executemany(
                """
                INSERT INTO rounds (id, slug, name, duration_seconds, cut_size, playable)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ROUND_SEED,
            )
    for folder in ("uploads", "references", "round_files"):
        target = settings.data_dir / folder
        if target.exists():
            for path in target.iterdir():
                if path.is_file():
                    path.unlink()


def rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def one(conn: sqlite3.Connection, query: str, params: tuple = ()) -> dict | None:
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


def log_action(conn: sqlite3.Connection, action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO admin_actions (at, action, detail) VALUES (?, ?, ?)",
        (stamp(), action, detail),
    )


def abs_stored(settings: Settings, stored: str) -> Path:
    root = settings.data_dir.resolve()
    path = (settings.data_dir / stored).resolve()
    if root != path and root not in path.parents:
        raise AppError("Bad stored path", 400)
    return path


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def generate_codes(settings: Settings, count: int) -> list[str]:
    if count < 1 or count > 200:
        raise AppError("Generate between 1 and 200 codes at a time")
    created: list[str] = []
    with WRITE:
        with connect(settings) as conn:
            while len(created) < count:
                code = new_code()
                try:
                    conn.execute(
                        "INSERT INTO participants (code, created_at) VALUES (?, ?)",
                        (code, stamp()),
                    )
                except sqlite3.IntegrityError:
                    continue
                created.append(code)
            log_action(conn, "codes", f"Generated {count} codes")
    return created


def all_codes(settings: Settings) -> list[dict]:
    with connect(settings) as conn:
        return rows(conn, "SELECT id, code, created_at FROM participants ORDER BY id")


def participant_by_code(settings: Settings, code: str) -> dict | None:
    with connect(settings) as conn:
        return one(conn, "SELECT * FROM participants WHERE code = ?", (code.strip().upper(),))


def participant_by_token(settings: Settings, token: str) -> dict | None:
    with connect(settings) as conn:
        return one(conn, "SELECT * FROM participants WHERE session_token = ?", (token,))


def start_player_session(settings: Settings, code: str) -> tuple[dict, str]:
    cleaned = code.strip().upper()
    if not cleaned:
        raise AppError("Enter your code", 400)
    token = secrets.token_urlsafe(32)
    with WRITE:
        with connect(settings) as conn:
            row = one(conn, "SELECT * FROM participants WHERE code = ?", (cleaned,))
            if not row:
                raise AppError("That code is not on the list", 401)
            conn.execute("UPDATE participants SET session_token = ? WHERE id = ?", (token, row["id"]))
            row["session_token"] = token
    return row, token


def clear_player_session(settings: Settings, token: str) -> None:
    with WRITE:
        with connect(settings) as conn:
            conn.execute("UPDATE participants SET session_token = NULL WHERE session_token = ?", (token,))


def _same(left: str, right: str) -> bool:
    import hmac

    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def start_admin_session(settings: Settings, username: str, password: str) -> str:
    if not (_same(username, settings.admin_username) and _same(password, settings.admin_password)):
        raise AppError("Wrong admin login", 401)
    token = secrets.token_urlsafe(32)
    with WRITE:
        with connect(settings) as conn:
            conn.execute(
                "INSERT INTO admin_sessions (token, created_at) VALUES (?, ?)",
                (token, stamp()),
            )
    return token


def admin_token_ok(settings: Settings, token: str | None) -> bool:
    if not token:
        return False
    with connect(settings) as conn:
        return one(conn, "SELECT token FROM admin_sessions WHERE token = ?", (token,)) is not None


def clear_admin_session(settings: Settings, token: str) -> None:
    with WRITE:
        with connect(settings) as conn:
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


def get_round(conn: sqlite3.Connection, round_id: int) -> dict:
    row = one(conn, "SELECT * FROM rounds WHERE id = ?", (round_id,))
    if not row:
        raise AppError("Unknown round", 404)
    return row


def live_round(conn: sqlite3.Connection) -> dict | None:
    return one(conn, "SELECT * FROM rounds WHERE status = 'live' ORDER BY id LIMIT 1")


def references_for(conn: sqlite3.Connection, round_id: int) -> list[dict]:
    return rows(
        conn,
        "SELECT * FROM reference_images WHERE round_id = ? ORDER BY slot",
        (round_id,),
    )


def rank_round(conn: sqlite3.Connection, round_id: int) -> list[dict]:
    participants = rows(conn, "SELECT * FROM participants ORDER BY code")
    submissions = rows(conn, "SELECT * FROM submissions WHERE round_id = ?", (round_id,))
    reference_ids = [row["id"] for row in references_for(conn, round_id)]
    return rank_participants(participants, submissions, reference_ids)


def is_eligible(conn: sqlite3.Connection, participant_id: int, round_id: int) -> bool:
    if round_id == 1:
        return True
    previous = one(conn, "SELECT * FROM rounds WHERE id = ?", (round_id - 1,))
    if not previous or not previous["advancement_confirmed"]:
        return False
    row = one(
        conn,
        """
        SELECT included FROM advancement
        WHERE from_round_id = ? AND participant_id = ? AND included = 1
        """,
        (round_id - 1, participant_id),
    )
    return row is not None


def _fill_suggestion(conn: sqlite3.Connection, round_id: int) -> None:
    rnd = get_round(conn, round_id)
    ranked = rank_round(conn, round_id)
    conn.execute("DELETE FROM advancement WHERE from_round_id = ?", (round_id,))
    conn.executemany(
        """
        INSERT INTO advancement (from_round_id, participant_id, included)
        VALUES (?, ?, ?)
        """,
        [
            (round_id, row["participant_id"], 1 if index < rnd["cut_size"] else 0)
            for index, row in enumerate(ranked)
        ],
    )
    conn.execute("UPDATE rounds SET advancement_confirmed = 0 WHERE id = ?", (round_id,))


def close_if_expired(settings: Settings) -> None:
    with WRITE:
        with connect(settings) as conn:
            rnd = live_round(conn)
            if not rnd or not rnd["ends_at"]:
                return
            if parse_stamp(rnd["ends_at"]) <= utcnow():
                _end_round(conn, rnd["id"], "auto-end")


def _end_round(conn: sqlite3.Connection, round_id: int, action: str) -> None:
    rnd = get_round(conn, round_id)
    if rnd["status"] != "live":
        if action == "auto-end":
            return
        raise AppError("Round is not live")
    conn.execute(
        """
        UPDATE rounds
        SET status = 'ended', ends_at = ?, advancement_confirmed = 0
        WHERE id = ?
        """,
        (stamp(), round_id),
    )
    _fill_suggestion(conn, round_id)
    log_action(conn, action, f"Ended {rnd['name']}")


def end_round(settings: Settings, round_id: int) -> None:
    close_if_expired(settings)
    with WRITE:
        with connect(settings) as conn:
            _end_round(conn, round_id, "end")


def update_settings(
    settings: Settings,
    round_id: int,
    duration_minutes: int,
    cut_size: int,
    notes: str,
) -> None:
    if duration_minutes < 1 or duration_minutes > 240:
        raise AppError("Duration must be between 1 and 240 minutes")
    if cut_size < 1 or cut_size > 1000:
        raise AppError("Cut size must be between 1 and 1000")
    notes = notes[:4000]
    with WRITE:
        with connect(settings) as conn:
            rnd = get_round(conn, round_id)
            if rnd["advancement_frozen"] and cut_size != rnd["cut_size"]:
                raise AppError("This advance list is frozen")
            duration = rnd["duration_seconds"]
            if rnd["status"] == "draft":
                duration = duration_minutes * 60
            conn.execute(
                """
                UPDATE rounds
                SET duration_seconds = ?, cut_size = ?, notes = ?
                WHERE id = ?
                """,
                (duration, cut_size, notes, round_id),
            )
            log_action(
                conn,
                "settings",
                f"{rnd['name']}: cut {cut_size}, duration {duration // 60} min",
            )


def ensure_calibration(settings: Settings, scorer, reference: dict) -> None:
    with connect(settings) as conn:
        existing = one(
            conn,
            "SELECT reference_id FROM calibration WHERE reference_id = ?",
            (reference["id"],),
        )
    if existing:
        return
    floor, ceiling = scorer.calibration_bounds(abs_stored(settings, reference["stored_path"]))
    with WRITE:
        with connect(settings) as conn:
            conn.execute(
                """
                INSERT INTO calibration (
                    reference_id, lpips_floor, lpips_ceiling, ssim_floor, ssim_ceiling,
                    dino_floor, dino_ceiling
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reference_id) DO UPDATE SET
                    lpips_floor = excluded.lpips_floor,
                    lpips_ceiling = excluded.lpips_ceiling,
                    ssim_floor = excluded.ssim_floor,
                    ssim_ceiling = excluded.ssim_ceiling,
                    dino_floor = excluded.dino_floor,
                    dino_ceiling = excluded.dino_ceiling
                """,
                (
                    reference["id"],
                    floor.lpips,
                    ceiling.lpips,
                    floor.ssim,
                    ceiling.ssim,
                    floor.dino,
                    ceiling.dino,
                ),
            )


def save_reference(
    settings: Settings,
    scorer,
    round_id: int,
    slot: int,
    data: bytes,
    media_type: str,
    digest: str,
) -> dict:
    if slot not in (1, 2, 3):
        raise AppError("Image slot must be 1, 2, or 3")
    suffix = ".png" if media_type == "image/png" else ".jpg"
    stored = f"references/round{round_id}_slot{slot}{suffix}"
    target = abs_stored(settings, stored)
    with WRITE:
        with connect(settings) as conn:
            rnd = get_round(conn, round_id)
            if rnd["status"] != "draft":
                raise AppError("Images can be replaced only while the round is in draft. Restart first.")
            if not rnd["playable"]:
                raise AppError("This round does not take reference images")
            previous = one(
                conn,
                "SELECT * FROM reference_images WHERE round_id = ? AND slot = ?",
                (round_id, slot),
            )
            target.write_bytes(data)
            if previous:
                conn.execute("DELETE FROM calibration WHERE reference_id = ?", (previous["id"],))
                conn.execute(
                    """
                    UPDATE reference_images
                    SET stored_path = ?, sha256 = ?, media_type = ?
                    WHERE id = ?
                    """,
                    (stored, digest, media_type, previous["id"]),
                )
                reference = one(conn, "SELECT * FROM reference_images WHERE id = ?", (previous["id"],))
            else:
                cur = conn.execute(
                    """
                    INSERT INTO reference_images (round_id, slot, stored_path, sha256, media_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (round_id, slot, stored, digest, media_type),
                )
                reference = one(
                    conn,
                    "SELECT * FROM reference_images WHERE id = ?",
                    (cur.lastrowid,),
                )
            log_action(conn, "image", f"Set {rnd['name']} reference slot {slot}")
    ensure_calibration(settings, scorer, reference)
    return reference


def activate_round(settings: Settings, scorer, round_id: int) -> None:
    close_if_expired(settings)
    with connect(settings) as conn:
        rnd = get_round(conn, round_id)
        refs = references_for(conn, round_id)
    if not rnd["playable"]:
        raise AppError("This round has no attempt page yet.")
    if rnd["status"] != "draft":
        raise AppError("Only a draft round can be activated")
    if len(refs) < 3:
        raise AppError("Upload all 3 reference images first")
    for ref in refs:
        ensure_calibration(settings, scorer, ref)
    with WRITE:
        with connect(settings) as conn:
            if live_round(conn):
                raise AppError("Another round is already live")
            rnd = get_round(conn, round_id)
            if rnd["status"] != "draft":
                raise AppError("Only a draft round can be activated")
            now = utcnow()
            ends = now + timedelta(seconds=rnd["duration_seconds"])
            conn.execute(
                """
                UPDATE rounds
                SET status = 'live', started_at = ?, ends_at = ?
                WHERE id = ?
                """,
                (stamp(now), stamp(ends), round_id),
            )
            if round_id > 1:
                conn.execute(
                    "UPDATE rounds SET advancement_frozen = 1 WHERE id = ?",
                    (round_id - 1,),
                )
            log_action(conn, "activate", f"Activated {rnd['name']}")


def extend_round(settings: Settings, round_id: int, minutes: int) -> None:
    if minutes < 1 or minutes > 180:
        raise AppError("Add between 1 and 180 minutes")
    close_if_expired(settings)
    with WRITE:
        with connect(settings) as conn:
            rnd = get_round(conn, round_id)
            if rnd["advancement_frozen"]:
                raise AppError("This advance list is frozen")
            if rnd["status"] == "draft":
                raise AppError("Change the duration before the round starts")
            if rnd["status"] == "live":
                ends = parse_stamp(rnd["ends_at"]) + timedelta(minutes=minutes)
                conn.execute("UPDATE rounds SET ends_at = ? WHERE id = ?", (stamp(ends), round_id))
                log_action(conn, "extend", f"Added {minutes} minutes to {rnd['name']}")
                return
            conn.execute("DELETE FROM advancement WHERE from_round_id = ?", (round_id,))
            ends = utcnow() + timedelta(minutes=minutes)
            conn.execute(
                """
                UPDATE rounds
                SET status = 'live', ends_at = ?, advancement_confirmed = 0
                WHERE id = ?
                """,
                (stamp(ends), round_id),
            )
            log_action(conn, "extend", f"Reopened {rnd['name']} for {minutes} minutes")


def restart_round(settings: Settings, round_id: int, confirm: str) -> None:
    if confirm != "RESTART":
        raise AppError("Type RESTART to throw away this round's uploads and scores")
    with WRITE:
        with connect(settings) as conn:
            rnd = get_round(conn, round_id)
            if rnd["advancement_frozen"]:
                raise AppError("This advance list is frozen")
            if rnd["status"] == "draft":
                raise AppError("The round is already in draft")
            stored = rows(
                conn,
                "SELECT stored_path FROM submissions WHERE round_id = ?",
                (round_id,),
            )
            ref_ids = [row["id"] for row in references_for(conn, round_id)]
            conn.execute("DELETE FROM submissions WHERE round_id = ?", (round_id,))
            if ref_ids:
                marks = ",".join("?" for _ in ref_ids)
                conn.execute(
                    f"DELETE FROM slot_errors WHERE reference_id IN ({marks})",
                    tuple(ref_ids),
                )
            conn.execute("DELETE FROM advancement WHERE from_round_id = ?", (round_id,))
            conn.execute(
                """
                UPDATE rounds
                SET status = 'draft', started_at = NULL, ends_at = NULL,
                    advancement_confirmed = 0, advancement_frozen = 0
                WHERE id = ?
                """,
                (round_id,),
            )
            log_action(conn, "restart", f"Restarted {rnd['name']}")
    for row in stored:
        path = abs_stored(settings, row["stored_path"])
        if path.exists():
            path.unlink()


def suggest(settings: Settings, round_id: int) -> None:
    with WRITE:
        with connect(settings) as conn:
            rnd = get_round(conn, round_id)
            if rnd["advancement_frozen"]:
                raise AppError("This advance list is frozen")
            if rnd["status"] != "ended":
                raise AppError("Suggest the cut after the round ends")
            _fill_suggestion(conn, round_id)
            log_action(conn, "suggest", f"Suggested top {rnd['cut_size']} for {rnd['name']}")


def set_advancement(settings: Settings, round_id: int, participant_ids: list[int]) -> None:
    chosen = set(participant_ids)
    with WRITE:
        with connect(settings) as conn:
            rnd = get_round(conn, round_id)
            if rnd["advancement_frozen"]:
                raise AppError("This advance list is frozen")
            if rnd["status"] != "ended":
                raise AppError("Choose who advances after the round ends")
            known = {row["id"] for row in rows(conn, "SELECT id FROM participants")}
            unknown = chosen - known
            if unknown:
                raise AppError("Unknown participant in the advance list")
            ranked = rank_round(conn, round_id)
            conn.execute("DELETE FROM advancement WHERE from_round_id = ?", (round_id,))
            conn.executemany(
                """
                INSERT INTO advancement (from_round_id, participant_id, included)
                VALUES (?, ?, ?)
                """,
                [
                    (round_id, row["participant_id"], 1 if row["participant_id"] in chosen else 0)
                    for row in ranked
                ],
            )
            conn.execute("UPDATE rounds SET advancement_confirmed = 0 WHERE id = ?", (round_id,))
            log_action(conn, "selection", f"Saved {len(chosen)} people to advance from {rnd['name']}")


def confirm_advancement(settings: Settings, round_id: int) -> None:
    with WRITE:
        with connect(settings) as conn:
            rnd = get_round(conn, round_id)
            if rnd["advancement_frozen"]:
                raise AppError("This advance list is frozen")
            if rnd["status"] != "ended":
                raise AppError("End the round before confirming who advances")
            conn.execute(
                "UPDATE rounds SET advancement_confirmed = 1 WHERE id = ?",
                (round_id,),
            )
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM advancement WHERE from_round_id = ? AND included = 1",
                (round_id,),
            ).fetchone()["n"]
            log_action(conn, "confirm", f"Confirmed {count} people advancing from {rnd['name']}")


def void_submission(settings: Settings, submission_id: int) -> None:
    with WRITE:
        with connect(settings) as conn:
            row = one(conn, "SELECT * FROM submissions WHERE id = ?", (submission_id,))
            if not row:
                raise AppError("Submission not found", 404)
            if row["status"] != "scored":
                raise AppError("Wait until this upload finishes scoring")
            conn.execute("UPDATE submissions SET voided = 1 WHERE id = ?", (submission_id,))
            log_action(conn, "void", f"Voided submission {submission_id}")


def screen_for(conn: sqlite3.Connection, participant_id: int) -> tuple[str, dict | None]:
    live = live_round(conn)
    if live:
        if not is_eligible(conn, participant_id, live["id"]):
            return "blocked", live
        if not live["playable"]:
            return "unavailable", live
        return "play", live
    ended = one(conn, "SELECT * FROM rounds WHERE status = 'ended' ORDER BY id DESC LIMIT 1")
    if not ended:
        return "waiting", one(conn, "SELECT * FROM rounds WHERE id = 1")
    if not ended["advancement_confirmed"]:
        return "standby", ended
    included = one(
        conn,
        """
        SELECT included FROM advancement
        WHERE from_round_id = ? AND participant_id = ? AND included = 1
        """,
        (ended["id"], participant_id),
    )
    return ("advanced" if included else "out"), ended


def accept_upload(
    settings: Settings,
    participant_id: int,
    reference_slot: int,
    attempt: int,
    prompt: str,
    data: bytes,
    digest: str,
    media_type: str,
) -> int:
    if reference_slot not in (1, 2, 3):
        raise AppError("Pick image 1, 2, or 3")
    if attempt not in (1, 2):
        raise AppError("Each image has attempt 1 and attempt 2")
    if len(prompt) > 2000:
        raise AppError("Prompt note is limited to 2000 characters")
    suffix = ".png" if media_type == "image/png" else ".jpg"
    stored = f"uploads/{secrets.token_hex(16)}{suffix}"
    abs_stored(settings, stored).write_bytes(data)
    try:
        with WRITE:
            with connect(settings) as conn:
                rnd = live_round(conn)
                if rnd and rnd["ends_at"] and parse_stamp(rnd["ends_at"]) <= utcnow():
                    _end_round(conn, rnd["id"], "auto-end")
                    rnd = None
                if not rnd:
                    raise AppError("The round is not accepting uploads")
                if not is_eligible(conn, participant_id, rnd["id"]):
                    raise AppError("You are not eligible for this round", 403)
                reference = one(
                    conn,
                    "SELECT * FROM reference_images WHERE round_id = ? AND slot = ?",
                    (rnd["id"], reference_slot),
                )
                if not reference:
                    raise AppError("That reference image is not set")
                existing = one(
                    conn,
                    """
                    SELECT id FROM submissions
                    WHERE participant_id = ? AND reference_id = ? AND slot = ?
                    """,
                    (participant_id, reference["id"], attempt),
                )
                if existing:
                    raise AppError("That slot is already used", 409)
                conn.execute(
                    """
                    DELETE FROM slot_errors
                    WHERE participant_id = ? AND reference_id = ? AND slot = ?
                    """,
                    (participant_id, reference["id"], attempt),
                )
                cur = conn.execute(
                    """
                    INSERT INTO submissions (
                        participant_id, round_id, reference_id, slot, stored_path, sha256,
                        media_type, prompt_text, status, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                    """,
                    (
                        participant_id,
                        rnd["id"],
                        reference["id"],
                        attempt,
                        stored,
                        digest,
                        media_type,
                        prompt.strip(),
                        stamp(),
                    ),
                )
                return int(cur.lastrowid)
    except AppError:
        path = abs_stored(settings, stored)
        if path.exists():
            path.unlink()
        raise
    except sqlite3.IntegrityError as exc:
        path = abs_stored(settings, stored)
        if path.exists():
            path.unlink()
        raise AppError("That slot is already used", 409) from exc


def fail_submission(settings: Settings, submission_id: int, message: str) -> None:
    with WRITE:
        with connect(settings) as conn:
            row = one(conn, "SELECT * FROM submissions WHERE id = ?", (submission_id,))
            if not row or row["status"] != "queued":
                return
            conn.execute(
                """
                INSERT INTO slot_errors (participant_id, reference_id, slot, message, at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(participant_id, reference_id, slot) DO UPDATE SET
                    message = excluded.message, at = excluded.at
                """,
                (row["participant_id"], row["reference_id"], row["slot"], message[:300], stamp()),
            )
            conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
            stored = row["stored_path"]
    path = abs_stored(settings, stored)
    if path.exists():
        path.unlink()


def complete_submission(settings: Settings, submission_id: int, scored: dict) -> None:
    with WRITE:
        with connect(settings) as conn:
            row = one(conn, "SELECT id, status FROM submissions WHERE id = ?", (submission_id,))
            if not row or row["status"] != "queued":
                return
            conn.execute(
                """
                UPDATE submissions SET
                    status = 'scored',
                    lpips_raw = ?, ssim_raw = ?, dino_raw = ?,
                    lpips_score = ?, ssim_score = ?, dino_score = ?,
                    total_score = ?, flag_reason = ?, scored_at = ?
                WHERE id = ?
                """,
                (
                    scored["lpips_raw"],
                    scored["ssim_raw"],
                    scored["dino_raw"],
                    scored["lpips_score"],
                    scored["ssim_score"],
                    scored["dino_score"],
                    scored["total_score"],
                    scored["flag_reason"],
                    stamp(),
                    submission_id,
                ),
            )


def queued_submission(settings: Settings, submission_id: int) -> dict | None:
    with connect(settings) as conn:
        row = one(
            conn,
            """
            SELECT s.*, r.stored_path AS reference_path, c.lpips_floor, c.lpips_ceiling,
                   c.ssim_floor, c.ssim_ceiling, c.dino_floor, c.dino_ceiling
            FROM submissions s
            JOIN reference_images r ON r.id = s.reference_id
            LEFT JOIN calibration c ON c.reference_id = r.id
            WHERE s.id = ?
            """,
            (submission_id,),
        )
    return row


def player_state(settings: Settings, participant: dict) -> dict:
    close_if_expired(settings)
    with connect(settings) as conn:
        screen, rnd = screen_for(conn, participant["id"])
        ranked = rank_round(conn, rnd["id"]) if rnd else []
        mine = next((row for row in ranked if row["participant_id"] == participant["id"]), None)
        images = []
        if screen == "play" and rnd:
            refs = references_for(conn, rnd["id"])
            subs = rows(
                conn,
                "SELECT * FROM submissions WHERE participant_id = ? AND round_id = ?",
                (participant["id"], rnd["id"]),
            )
            errors = rows(
                conn,
                """
                SELECT se.* FROM slot_errors se
                JOIN reference_images r ON r.id = se.reference_id
                WHERE se.participant_id = ? AND r.round_id = ?
                """,
                (participant["id"], rnd["id"]),
            )
            by_ref = {}
            for sub in subs:
                by_ref.setdefault(sub["reference_id"], {})[sub["slot"]] = sub
            err_map = {(row["reference_id"], row["slot"]): row["message"] for row in errors}
            counting = {item["reference_id"]: item for item in (mine["images"] if mine else [])}
            for ref in refs:
                attempts = []
                for slot in (1, 2):
                    sub = by_ref.get(ref["id"], {}).get(slot)
                    if sub:
                        attempts.append(
                            {
                                "attempt": slot,
                                "status": sub["status"],
                                "total_score": sub["total_score"],
                                "submitted_at": sub["submitted_at"],
                            }
                        )
                    elif (ref["id"], slot) in err_map:
                        attempts.append(
                            {
                                "attempt": slot,
                                "status": "error",
                                "error": err_map[(ref["id"], slot)],
                            }
                        )
                    else:
                        attempts.append({"attempt": slot, "status": "empty"})
                counted = counting.get(ref["id"], {})
                images.append(
                    {
                        "reference_id": ref["id"],
                        "slot": ref["slot"],
                        "url": f"/media/reference/{ref['id']}",
                        "counting_score": counted.get("counting_score", 0),
                        "counting_attempt": counted.get("counting_slot"),
                        "attempts": attempts,
                    }
                )
        messages = {
            "waiting": "You're in. Waiting for Image Wars to start.",
            "blocked": "You can't attempt this round.",
            "standby": "Round over. Stand by for results.",
            "advanced": "You advanced. Waiting for the next round.",
            "out": "You did not advance.",
            "unavailable": "This round is not open for attempts.",
            "play": "",
        }
        return {
            "participant": {"id": participant["id"], "code": participant["code"]},
            "server_now": stamp(),
            "screen": screen,
            "message": messages[screen],
            "round": None
            if not rnd
            else {
                "id": rnd["id"],
                "name": rnd["name"],
                "status": rnd["status"],
                "ends_at": rnd["ends_at"],
                "score": None if not mine else mine["total"],
                "rank": None if not mine else mine["rank"],
                "player_count": len(ranked),
                "images": images,
            },
        }


def _advance_rows(conn: sqlite3.Connection, round_id: int, ranked: list[dict]) -> list[dict]:
    flags = {
        row["participant_id"]: row["included"]
        for row in rows(conn, "SELECT * FROM advancement WHERE from_round_id = ?", (round_id,))
    }
    return [
        {
            "participant_id": row["participant_id"],
            "code": row["code"],
            "included": bool(flags.get(row["participant_id"], 0)),
            "rank": row["rank"],
            "total": row["total"],
        }
        for row in ranked
    ]


def admin_state(settings: Settings, scoring_mode: str) -> dict:
    close_if_expired(settings)
    with connect(settings) as conn:
        rounds = rows(conn, "SELECT * FROM rounds ORDER BY id")
        payload = []
        for rnd in rounds:
            refs = references_for(conn, rnd["id"])
            files = rows(
                conn,
                "SELECT id, filename, uploaded_at FROM round_files WHERE round_id = ? ORDER BY id",
                (rnd["id"],),
            )
            ranked = rank_round(conn, rnd["id"])
            subs = rows(conn, "SELECT * FROM submissions WHERE round_id = ?", (rnd["id"],))
            by_person: dict[int, list[dict]] = {}
            for sub in subs:
                by_person.setdefault(sub["participant_id"], []).append(sub)
            board = []
            for row in ranked:
                person_subs = by_person.get(row["participant_id"], [])
                board.append({**row, "submissions": _public_submissions(person_subs, refs)})
            entrants = _entrants(conn, rnd["id"])
            payload.append(
                {
                    "id": rnd["id"],
                    "name": rnd["name"],
                    "slug": rnd["slug"],
                    "status": rnd["status"],
                    "playable": bool(rnd["playable"]),
                    "duration_minutes": rnd["duration_seconds"] // 60,
                    "cut_size": rnd["cut_size"],
                    "notes": rnd["notes"],
                    "started_at": rnd["started_at"],
                    "ends_at": rnd["ends_at"],
                    "advancement_confirmed": bool(rnd["advancement_confirmed"]),
                    "advancement_frozen": bool(rnd["advancement_frozen"]),
                    "references": [
                        {
                            "id": ref["id"],
                            "slot": ref["slot"],
                            "url": f"/media/reference/{ref['id']}",
                        }
                        for ref in refs
                    ],
                    "files": files,
                    "leaderboard": board,
                    "advancement": _advance_rows(conn, rnd["id"], ranked),
                    "entrants": entrants,
                }
            )
        actions = rows(
            conn,
            "SELECT at, action, detail FROM admin_actions ORDER BY id DESC LIMIT 80",
        )
    return {
        "server_now": stamp(),
        "scoring_mode": scoring_mode,
        "codes": all_codes(settings),
        "actions": actions,
        "rounds": payload,
    }


def _public_submissions(subs: list[dict], refs: list[dict]) -> list[dict]:
    by_ref = {ref["id"]: ref["slot"] for ref in refs}
    published = []
    for sub in subs:
        published.append(
            {
                "id": sub["id"],
                "image_slot": by_ref.get(sub["reference_id"]),
                "attempt": sub["slot"],
                "status": sub["status"],
                "total_score": sub["total_score"],
                "lpips_raw": sub["lpips_raw"],
                "ssim_raw": sub["ssim_raw"],
                "dino_raw": sub["dino_raw"],
                "flag_reason": sub["flag_reason"],
                "voided": bool(sub["voided"]),
                "prompt_text": sub["prompt_text"],
                "submitted_at": sub["submitted_at"],
                "url": f"/media/submission/{sub['id']}",
            }
        )
    return published


def _entrants(conn: sqlite3.Connection, round_id: int) -> list[dict]:
    if round_id == 1:
        return rows(conn, "SELECT id AS participant_id, code FROM participants ORDER BY code")
    previous = one(conn, "SELECT advancement_confirmed FROM rounds WHERE id = ?", (round_id - 1,))
    if not previous or not previous["advancement_confirmed"]:
        return []
    return rows(
        conn,
        """
        SELECT p.id AS participant_id, p.code
        FROM advancement a
        JOIN participants p ON p.id = a.participant_id
        WHERE a.from_round_id = ? AND a.included = 1
        ORDER BY p.code
        """,
        (round_id - 1,),
    )


def save_round_file(settings: Settings, round_id: int, filename: str, data: bytes) -> None:
    if round_id == 1:
        raise AppError("Round 1 uses the three reference image slots")
    safe = Path(filename).name or "file"
    stored = f"round_files/{secrets.token_hex(8)}_{safe}"
    abs_stored(settings, stored).write_bytes(data)
    with WRITE:
        with connect(settings) as conn:
            get_round(conn, round_id)
            conn.execute(
                """
                INSERT INTO round_files (round_id, filename, stored_path, uploaded_at)
                VALUES (?, ?, ?, ?)
                """,
                (round_id, safe, stored, stamp()),
            )
            log_action(conn, "file", f"Stored material {safe} on round {round_id}")


def delete_round_file(settings: Settings, round_id: int, file_id: int) -> None:
    with WRITE:
        with connect(settings) as conn:
            row = one(
                conn,
                "SELECT * FROM round_files WHERE id = ? AND round_id = ?",
                (file_id, round_id),
            )
            if not row:
                raise AppError("File not found", 404)
            conn.execute("DELETE FROM round_files WHERE id = ?", (file_id,))
            log_action(conn, "file", f"Removed material {row['filename']}")
            stored = row["stored_path"]
    path = abs_stored(settings, stored)
    if path.exists():
        path.unlink()


def reference_for_media(settings: Settings, reference_id: int, participant: dict | None, is_admin: bool) -> dict:
    with connect(settings) as conn:
        ref = one(conn, "SELECT * FROM reference_images WHERE id = ?", (reference_id,))
        if not ref:
            raise AppError("Image not found", 404)
        rnd = get_round(conn, ref["round_id"])
        if is_admin:
            return ref
        if not participant:
            raise AppError("Login required", 401)
        if rnd["status"] == "live" and is_eligible(conn, participant["id"], rnd["id"]):
            return ref
        raise AppError("That image is not available", 403)


def submission_for_media(settings: Settings, submission_id: int, participant: dict | None, is_admin: bool) -> dict:
    with connect(settings) as conn:
        row = one(conn, "SELECT * FROM submissions WHERE id = ?", (submission_id,))
        if not row:
            raise AppError("Upload not found", 404)
        if is_admin or (participant and participant["id"] == row["participant_id"]):
            return row
        raise AppError("That upload is not available", 403)


def export_csv(settings: Settings, round_id: int) -> str:
    close_if_expired(settings)
    with connect(settings) as conn:
        get_round(conn, round_id)
        refs = references_for(conn, round_id)
        ranked = rank_round(conn, round_id)
        included = {
            row["participant_id"]: row["included"]
            for row in rows(conn, "SELECT * FROM advancement WHERE from_round_id = ?", (round_id,))
        }
        subs = rows(conn, "SELECT * FROM submissions WHERE round_id = ?", (round_id,))
    by_person: dict[int, list[dict]] = {}
    for sub in subs:
        by_person.setdefault(sub["participant_id"], []).append(sub)
    buffer = io.StringIO()
    header = ["code", "rank", "total", "lpips_sum", "achieved_at", "checked_to_advance"]
    for ref in refs:
        header.extend(
            [
                f"image{ref['slot']}_counting",
                f"image{ref['slot']}_attempt1",
                f"image{ref['slot']}_attempt2",
                f"image{ref['slot']}_attempt1_flag",
                f"image{ref['slot']}_attempt2_flag",
                f"image{ref['slot']}_attempt1_void",
                f"image{ref['slot']}_attempt2_void",
            ]
        )
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in ranked:
        person = by_person.get(row["participant_id"], [])
        record = [
            row["code"],
            row["rank"],
            f"{row['total']:.4f}",
            f"{row['lpips_sum']:.4f}",
            row["achieved_at"] or "",
            "yes" if included.get(row["participant_id"]) else "no",
        ]
        counting = {item["reference_id"]: item for item in row["images"]}
        for ref in refs:
            slots = {sub["slot"]: sub for sub in person if sub["reference_id"] == ref["id"]}
            counted = counting.get(ref["id"], {})
            record.append(f"{counted.get('counting_score', 0):.4f}")
            for slot in (1, 2):
                sub = slots.get(slot)
                record.append("" if not sub or sub["total_score"] is None else f"{sub['total_score']:.4f}")
            for slot in (1, 2):
                sub = slots.get(slot)
                record.append("" if not sub else (sub["flag_reason"] or ""))
            for slot in (1, 2):
                sub = slots.get(slot)
                record.append("" if not sub else ("yes" if sub["voided"] else "no"))
        writer.writerow(record)
    return buffer.getvalue()


def write_codes_csv(settings: Settings) -> Path:
    target = settings.data_dir / "codes.csv"
    codes = all_codes(settings)
    with target.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code"])
        for row in codes:
            writer.writerow([row["code"]])
    return target
