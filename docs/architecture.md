# Architecture

One FastAPI process. SQLite file at `data/prompt_wars.db` with WAL enabled. Uploads, references, model weights, and generated code lists live under `data/`, which is gitignored.

Bind `0.0.0.0` and a port (default 8000) so phones on the same network can open `http://<laptop-ip>:8000/`.

```text
app/main.py            HTTP routes, pages, lifespan
app/config.py          env settings
app/db.py              schema, queries, round transitions
app/ranking.py         pure counting-score and rank functions
app/scoring.py         real scorer, fake scorer, calibration inputs
app/flags.py           hash, perceptual hash, SSIM threshold
app/worker.py          single-thread score queue
app/templates/         play.html, admin.html
app/static/            css and js, no external font host
scripts/generate_codes.py
scripts/calibrate.py
scripts/make_dev_references.py
tests/
```

Pages do not use a CDN. The event Wi-Fi may not have internet. Fonts are the system stack.

## Settings

Copied from `.env.example` into `.env`. `python-dotenv` loads `.env` without overriding variables that are already set, so tests can inject `DATA_DIR` and `SKIP_MODELS`.

| Variable | Meaning | Default in the example |
| --- | --- | --- |
| ADMIN_USERNAME | Admin panel login | admin |
| ADMIN_PASSWORD | Admin panel login | promptwars |
| DATA_DIR | SQLite, uploads, models | data |
| MAX_UPLOAD_MB | Player and admin image cap | 8 |
| HOST | Bind address | 0.0.0.0 |
| PORT | Bind port | 8000 |
| SKIP_MODELS | `1` uses the fake scorer | unset |

The example password is for a local dry run. Change it before the room arrives. `.env` is gitignored.

## Schema

`participants` — `id`, `code` unique, `session_token`, `created_at`.

`admin_sessions` — `token`, `created_at`.

`rounds` — one row each for ids 1, 2, 3.

- `slug`, `name`, `status` (`draft`, `live`, `ended`)
- `duration_seconds`, `cut_size`, `playable` (1 only for Round 1)
- `notes`, `started_at`, `ends_at`
- `advancement_confirmed`, `advancement_frozen` (0 or 1)

Seed: Round 1 Image Wars, 2400 seconds, cut 30, playable. Round 2 Black Box Cipher, 3000 seconds, cut 10, not playable. Round 3 Prompt to Precision, 1200 seconds, cut 3, not playable.

`reference_images` — `round_id`, `slot` 1–3, `stored_path`, `sha256`, `media_type`. Unique `(round_id, slot)`.

`calibration` — one row per reference image. Six reals: floor and ceiling for lpips, ssim, and dino.

`submissions` — one player attempt.

- `participant_id`, `round_id`, `reference_id`, `slot` 1 or 2
- `stored_path`, `sha256`, `media_type`, `prompt_text`
- `status` is `queued`, `scored`, or the row is deleted on scorer failure
- raw metrics, calibrated component scores, `total_score`
- `flag_reason` nullable, `voided`
- `submitted_at`, `scored_at`
- Unique `(participant_id, reference_id, slot)`

`slot_errors` — last scoring failure for a slot, primary key `(participant_id, reference_id, slot)`. Cleared when a new upload for that slot is accepted.

`advancement` — `from_round_id`, `participant_id`, `included`. Primary key `(from_round_id, participant_id)`. The confirmed and frozen bits live on `rounds`, not on each person.

`round_files` — admin material files for a round. `filename`, `stored_path`, `uploaded_at`.

`admin_actions` — `at`, `action`, `detail`.

## Rank and advance functions

`app/ranking.py` is pure. Given participant rows and submission rows, it returns the counting submission per image, the round score, the LPIPS sum, the achieved-at timestamp, and the ordered ranking. Route handlers and tests both call it. Do not reimplement that math in the templates.

## HTTP

Player cookies and admin cookies are separate. Routes under `/api/admin/` require the admin cookie. Player routes require the player cookie except login.

Player:

- `POST /api/login` JSON `{code}`
- `POST /api/logout`
- `GET /api/me` — screen state, timer, images, own scores, own rank. No flags.
- `POST /api/uploads` multipart fields `reference_slot`, `attempt`, `prompt`, `file`
- `GET /media/reference/{id}` — only while that round is live and the player is eligible, or with the admin cookie
- `GET /media/submission/{id}` — owner or admin

Admin:

- `POST /api/admin/login` JSON `{username, password}`
- `POST /api/admin/logout`
- `GET /api/admin/state` — rounds, images, files, leaderboard, flags, advance checkboxes, codes, action log, server time
- `POST /api/admin/codes` JSON `{count}`
- `POST /api/admin/rounds/{id}/settings` JSON `{duration_minutes, cut_size, notes}`
- `POST /api/admin/rounds/{id}/references/{slot}` multipart file
- `POST /api/admin/rounds/{id}/files` multipart file
- `DELETE /api/admin/rounds/{id}/files/{file_id}`
- `POST /api/admin/rounds/{id}/activate`
- `POST /api/admin/rounds/{id}/extend` JSON `{minutes}`
- `POST /api/admin/rounds/{id}/end`
- `POST /api/admin/rounds/{id}/restart` JSON `{confirm: "RESTART"}`
- `POST /api/admin/rounds/{id}/suggest`
- `PUT /api/admin/rounds/{id}/advancement` JSON `{participant_ids: [1, 2]}`
- `POST /api/admin/rounds/{id}/advancement/confirm`
- `POST /api/admin/submissions/{id}/void`
- `GET /api/admin/export.csv?round_id=1`

Errors are JSON `{"detail": "..."}` with a 4xx status. The UI shows `detail`.

`GET /api/me` and `GET /api/admin/state` and the upload route all close a live round whose `ends_at` is in the past before doing anything else. That transition is the same function as the admin End action, with action name `auto-end`.

## Scripts

- `python -m scripts.generate_codes 50` inserts codes and writes `data/codes.csv`.
- `python -m scripts.make_dev_references` writes three obviously different PNGs and registers them on Round 1 if those slots are empty. For dry runs only.
- `python -m scripts.calibrate` recomputes calibration with the real scorer and scores a pair twice.

## Tests

`pytest` sets `SKIP_MODELS=1` and a temporary `DATA_DIR` before importing the app. They cover ranking math, slot locks, late uploads, session replacement, eligibility, suggest/confirm, extend, restart, and the identical-file flag. They do not download DINOv2.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-scoring.txt
cp .env.example .env
python -m scripts.make_dev_references   # optional dry-run images
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Without `requirements-scoring.txt`, start only works if `SKIP_MODELS=1` is set in `.env`. That mode is for UI dry runs, not for the real event.
