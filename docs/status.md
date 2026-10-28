# Status

Updated as each core step lands. The next agent should trust this file over the plan file in `.cursor/plans`.

| Step | State | Notes |
| --- | --- | --- |
| Docs and decision log | done | This folder. |
| GitHub repo | done | Private repo `Ankritjarngal/prompt-wars`, branch `master`. |
| App scaffold | done | FastAPI, SQLite, requirements, `.env.example`. |
| Scoring and ranking | done | Real scorer in `app/scoring.py`. Tests use the fake scorer. |
| Player flow | done | `/` login, timer, 3 images, 2 slots, own total and rank. |
| Admin panel | done | Privileges in [admin-panel.md](admin-panel.md). Cut size is an editable number. |
| Tests | done | `pytest` covers rules, a 60-person custom cut (30, then 37), and 60 parallel uploads. |

The app runs. `SKIP_MODELS=1` is a dry run and is what the tests use. Event day installs `requirements-scoring.txt` and leaves `SKIP_MODELS` unset. Round 2 and Round 3 still have no attempt pages.
