from app.config import Settings
from app.db import connect, init_db, references_for, ensure_calibration
from app.scoring import build_scorer


def main() -> None:
    settings = Settings.from_env()
    if settings.skip_models:
        raise SystemExit("Unset SKIP_MODELS before calibrating real scores.")
    init_db(settings)
    scorer = build_scorer(settings)
    scorer.load()
    with connect(settings) as conn:
        refs = references_for(conn, 1)
    if len(refs) < 3:
        raise SystemExit("Upload 3 reference images first.")
    for ref in refs:
        from app.db import abs_stored

        path = abs_stored(settings, ref["stored_path"])
        with connect(settings) as conn:
            conn.execute("DELETE FROM calibration WHERE reference_id = ?", (ref["id"],))
        ensure_calibration(settings, scorer, ref)
        first = scorer.raw_pair(path, path)
        second = scorer.raw_pair(path, path)
        print(f"slot {ref['slot']} self-score {first} repeat {second} match={first == second}")


if __name__ == "__main__":
    main()
