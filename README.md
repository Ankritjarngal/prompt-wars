# Prompt Wars

Local web app for the Prompt Wars event. Round 1 (Image Wars) is the playable round: 3 reference images, 2 uploads each, best upload counts, round score is the sum out of 300.

Read [docs/README.md](docs/README.md) before changing behavior. That folder is the source of truth for rules, admin privileges, and decisions.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-scoring.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The scoring requirements are large because they include PyTorch. Set `SKIP_MODELS=1` in `.env` and install only `requirements.txt` for a UI dry run that does not score real images.
