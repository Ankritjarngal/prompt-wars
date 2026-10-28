from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.db import (
    AppError,
    abs_stored,
    accept_upload,
    activate_round,
    admin_state,
    admin_token_ok,
    clear_admin_session,
    clear_player_session,
    confirm_advancement,
    delete_round_file,
    end_round,
    export_csv,
    extend_round,
    generate_codes,
    init_db,
    participant_by_token,
    player_state,
    reference_for_media,
    restart_round,
    save_reference,
    save_round_file,
    set_advancement,
    start_admin_session,
    start_player_session,
    submission_for_media,
    suggest,
    update_settings,
    void_submission,
)
from app.images import inspect_image
from app.scoring import build_scorer
from app.worker import ScoreWorker

log = logging.getLogger("prompt_wars")
BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(settings)
        scorer = build_scorer(settings)
        scorer.load()
        app.state.scorer = scorer
        worker = ScoreWorker(settings, scorer)
        worker.start()
        app.state.worker = worker
        log.info("scoring mode: %s", "fake" if settings.skip_models else "real")
        yield
        worker.stop()

    app = FastAPI(title="Prompt Wars", lifespan=lifespan)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    def settings_of(request: Request) -> Settings:
        return request.app.state.settings

    def player(request: Request) -> dict:
        token = request.cookies.get("pw_session")
        row = participant_by_token(settings_of(request), token or "")
        if not row:
            raise AppError("Login required", 401)
        return row

    def require_admin(request: Request) -> None:
        if not admin_token_ok(settings_of(request), request.cookies.get("pw_admin")):
            raise AppError("Admin login required", 401)

    @app.get("/", response_class=HTMLResponse)
    def play_page(request: Request):
        return templates.TemplateResponse(request, "play.html")

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page(request: Request):
        return templates.TemplateResponse(request, "admin.html")

    @app.get("/api/health")
    def health(request: Request):
        return {"ok": True, "skip_models": settings_of(request).skip_models}

    @app.post("/api/login")
    def login(request: Request, payload: dict = Body(...)):
        _row, token = start_player_session(settings_of(request), str(payload.get("code", "")))
        response = JSONResponse({"ok": True})
        response.set_cookie("pw_session", token, httponly=True, samesite="lax", path="/", max_age=60 * 60 * 24 * 7)
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        token = request.cookies.get("pw_session")
        if token:
            clear_player_session(settings_of(request), token)
        response = JSONResponse({"ok": True})
        response.delete_cookie("pw_session", path="/")
        return response

    @app.get("/api/me")
    def me(request: Request):
        return player_state(settings_of(request), player(request))

    @app.post("/api/uploads")
    async def uploads(
        request: Request,
        reference_slot: int = Form(...),
        attempt: int = Form(...),
        prompt: str = Form(""),
        file: UploadFile = File(...),
    ):
        current = player(request)
        data = await file.read()
        media, digest = inspect_image(data, settings_of(request).max_upload_bytes)
        submission_id = accept_upload(
            settings_of(request),
            current["id"],
            reference_slot,
            attempt,
            prompt,
            data,
            digest,
            media,
        )
        request.app.state.worker.submit(submission_id)
        return {"id": submission_id, "status": "queued"}

    @app.get("/media/reference/{reference_id}")
    def media_reference(request: Request, reference_id: int):
        cfg = settings_of(request)
        is_admin = admin_token_ok(cfg, request.cookies.get("pw_admin"))
        current = None
        if not is_admin:
            token = request.cookies.get("pw_session")
            current = participant_by_token(cfg, token or "")
        ref = reference_for_media(cfg, reference_id, current, is_admin)
        path = abs_stored(cfg, ref["stored_path"])
        return FileResponse(path, media_type=ref["media_type"])

    @app.get("/media/submission/{submission_id}")
    def media_submission(request: Request, submission_id: int):
        cfg = settings_of(request)
        is_admin = admin_token_ok(cfg, request.cookies.get("pw_admin"))
        current = None
        if not is_admin:
            token = request.cookies.get("pw_session")
            current = participant_by_token(cfg, token or "")
        row = submission_for_media(cfg, submission_id, current, is_admin)
        path = abs_stored(cfg, row["stored_path"])
        return FileResponse(path, media_type=row["media_type"])

    @app.post("/api/admin/login")
    def admin_login(request: Request, payload: dict = Body(...)):
        token = start_admin_session(
            settings_of(request),
            str(payload.get("username", "")),
            str(payload.get("password", "")),
        )
        response = JSONResponse({"ok": True})
        response.set_cookie("pw_admin", token, httponly=True, samesite="lax", path="/", max_age=60 * 60 * 24 * 7)
        return response

    @app.post("/api/admin/logout")
    def admin_logout(request: Request):
        token = request.cookies.get("pw_admin")
        if token:
            clear_admin_session(settings_of(request), token)
        response = JSONResponse({"ok": True})
        response.delete_cookie("pw_admin", path="/")
        return response

    @app.get("/api/admin/state")
    def state(request: Request):
        require_admin(request)
        mode = "fake" if settings_of(request).skip_models else "real"
        return admin_state(settings_of(request), mode)

    @app.post("/api/admin/codes")
    def codes(request: Request, payload: dict = Body(...)):
        require_admin(request)
        created = generate_codes(settings_of(request), int(payload.get("count", 0)))
        return {"codes": created}

    @app.post("/api/admin/rounds/{round_id}/settings")
    def settings_route(request: Request, round_id: int, payload: dict = Body(...)):
        require_admin(request)
        update_settings(
            settings_of(request),
            round_id,
            int(payload.get("duration_minutes", 0)),
            int(payload.get("cut_size", 0)),
            str(payload.get("notes", "")),
        )
        return {"ok": True}

    @app.post("/api/admin/rounds/{round_id}/references/{slot}")
    async def upload_reference(request: Request, round_id: int, slot: int, file: UploadFile = File(...)):
        require_admin(request)
        data = await file.read()
        media, digest = inspect_image(data, settings_of(request).max_upload_bytes)
        save_reference(settings_of(request), request.app.state.scorer, round_id, slot, data, media, digest)
        return {"ok": True}

    @app.post("/api/admin/rounds/{round_id}/files")
    async def upload_material(request: Request, round_id: int, file: UploadFile = File(...)):
        require_admin(request)
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise AppError("Material files are limited to 20 MB")
        save_round_file(settings_of(request), round_id, file.filename or "file", data)
        return {"ok": True}

    @app.delete("/api/admin/rounds/{round_id}/files/{file_id}")
    def remove_material(request: Request, round_id: int, file_id: int):
        require_admin(request)
        delete_round_file(settings_of(request), round_id, file_id)
        return {"ok": True}

    @app.post("/api/admin/rounds/{round_id}/activate")
    def activate(request: Request, round_id: int):
        require_admin(request)
        activate_round(settings_of(request), request.app.state.scorer, round_id)
        return {"ok": True}

    @app.post("/api/admin/rounds/{round_id}/extend")
    def extend(request: Request, round_id: int, payload: dict = Body(...)):
        require_admin(request)
        extend_round(settings_of(request), round_id, int(payload.get("minutes", 0)))
        return {"ok": True}

    @app.post("/api/admin/rounds/{round_id}/end")
    def end(request: Request, round_id: int):
        require_admin(request)
        end_round(settings_of(request), round_id)
        return {"ok": True}

    @app.post("/api/admin/rounds/{round_id}/restart")
    def restart(request: Request, round_id: int, payload: dict = Body(...)):
        require_admin(request)
        restart_round(settings_of(request), round_id, str(payload.get("confirm", "")))
        return {"ok": True}

    @app.post("/api/admin/rounds/{round_id}/suggest")
    def suggest_route(request: Request, round_id: int):
        require_admin(request)
        suggest(settings_of(request), round_id)
        return {"ok": True}

    @app.put("/api/admin/rounds/{round_id}/advancement")
    def advancement(request: Request, round_id: int, payload: dict = Body(...)):
        require_admin(request)
        ids = [int(item) for item in payload.get("participant_ids", [])]
        set_advancement(settings_of(request), round_id, ids)
        return {"ok": True}

    @app.post("/api/admin/rounds/{round_id}/advancement/confirm")
    def confirm(request: Request, round_id: int):
        require_admin(request)
        confirm_advancement(settings_of(request), round_id)
        return {"ok": True}

    @app.post("/api/admin/submissions/{submission_id}/void")
    def void(request: Request, submission_id: int):
        require_admin(request)
        void_submission(settings_of(request), submission_id)
        return {"ok": True}

    @app.get("/api/admin/export.csv")
    def csv_export(request: Request, round_id: int = 1):
        require_admin(request)
        body = export_csv(settings_of(request), round_id)
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="round-{round_id}.csv"'},
        )

    return app


app = create_app()
