"""本地应用入口：python -m uvicorn Backend.main:app --host 127.0.0.1 --port 8000。"""

from contextlib import asynccontextmanager
from datetime import timezone
import logging
import os
from pathlib import Path
import secrets
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from Backend.config import DatabaseSettings
from Backend.database import check_connection, create_client, get_database
from Backend.init_db import initialize_database
from Backend.models import Credentials, DeadlineRequest, RevisionRequest, SurveyContent, SurveySave
from Backend.security import (
    COOKIE_NAME, DUMMY_HASH, current_user, normalize_username, password_hasher,
    public_user, start_session, token_hash, utcnow, verify_password,
)
from Backend.survey_service import owned_survey, serialize_survey, validate_content
from Backend.answer_service import public_survey_view
from Backend.answer_routes import router as answer_router
from Backend.question_routes import router as question_router, validate_sources


FRONTEND = Path(__file__).resolve().parent.parent / "Frontend"


def content_dict(payload: SurveyContent) -> dict:
    content = payload.model_dump(exclude={"draft_revision"})
    if content["settings"]["expires_at"] is not None:
        content["settings"]["expires_at"] = content["settings"]["expires_at"].astimezone(timezone.utc)
    for q in content["questions"]:
        q["validation"] = {key: value for key, value in q["validation"].items() if value is not None}
        if not q.get("source_question_id") and not q.get("source_version_id"):
            q.pop("source_question_id", None)
            q.pop("source_version_id", None)
    return content


def create_app(settings: DatabaseSettings | None = None, *, cookie_secure: bool | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        resolved = settings or DatabaseSettings.from_env()
        with create_client(resolved) as client:
            check_connection(client)
            db = get_database(client, resolved)
            initialize_database(db)
            application.state.db = db
            yield

    application = FastAPI(title="问卷工坊 API", version="0.3.0", lifespan=lifespan)
    application.state.cookie_secure = cookie_secure if cookie_secure is not None else os.getenv("SURVEY_COOKIE_SECURE") == "1"

    @application.middleware("http")
    async def browser_boundary(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "不允许跨站提交"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @application.exception_handler(PyMongoError)
    async def database_error(request, error):
        logging.getLogger(__name__).error("MongoDB request failed (%s)", type(error).__name__)
        return JSONResponse({"detail": "数据库暂时不可用，请稍后重试"}, status_code=503)

    @application.get("/api/health")
    def health(request: Request):
        request.app.state.db.command("ping")
        return {"status": "ok"}

    @application.post("/api/auth/register", status_code=201)
    def register(payload: Credentials, request: Request, response: Response):
        name, key = normalize_username(payload.username)
        user = {
            "schema_version": 1, "username": name, "username_key": key,
            "password_hash": password_hasher.hash(payload.password), "created_at": utcnow(),
        }
        try:
            request.app.state.db.users.insert_one(user)
        except DuplicateKeyError:
            raise HTTPException(409, "用户名已被使用") from None
        start_session(request, response, user["_id"])
        return public_user(user)

    @application.post("/api/auth/login")
    def login(payload: Credentials, request: Request, response: Response):
        _, key = normalize_username(payload.username)
        db = request.app.state.db
        user = db.users.find_one({"username_key": key})
        valid = verify_password(user["password_hash"] if user else DUMMY_HASH, payload.password)
        if not user or not valid:
            raise HTTPException(401, "用户名或密码错误")
        if password_hasher.check_needs_rehash(user["password_hash"]):
            db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": password_hasher.hash(payload.password)}})
        start_session(request, response, user["_id"])
        return public_user(user)

    @application.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return public_user(user)

    @application.post("/api/auth/logout", status_code=204)
    def logout(request: Request):
        token = request.cookies.get(COOKIE_NAME)
        if token and len(token) <= 128:
            request.app.state.db.sessions.delete_one({"token_hash": token_hash(token)})
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path="/", secure=request.app.state.cookie_secure, httponly=True, samesite="lax")
        return response

    @application.get("/api/surveys")
    def list_surveys(request: Request, offset: int = Query(0, ge=0), limit: int = Query(12, ge=1, le=100), status: Literal["draft", "published", "closed", "expired"] | None = None, user=Depends(current_user)):
        db = request.app.state.db
        query = {"owner_id": user["_id"]}
        now = utcnow()
        filters = {
            "draft": {"status": "draft"}, "closed": {"status": "closed"},
            "expired": {"status": "published", "settings.expires_at": {"$lte": now}},
            "published": {"status": "published", "$or": [{"settings.expires_at": None}, {"settings.expires_at": {"$gt": now}}]},
        }
        counts = {key: db.surveys.count_documents({**query, **condition}) for key, condition in filters.items()}
        if status:
            query.update(filters[status])
        records = list(db.surveys.find(query).sort([("created_at", -1), ("_id", -1)]).skip(offset).limit(limit))
        return {
            "items": [serialize_survey(s) for s in records],
            "total": db.surveys.count_documents(query), "offset": offset, "limit": limit, "counts": counts,
        }

    @application.post("/api/surveys", status_code=201)
    def create_survey(payload: SurveyContent, request: Request, user=Depends(current_user)):
        content = content_dict(payload)
        validate_content(content)
        validate_sources(request.app.state.db, content, user["_id"])
        now = utcnow()
        for _ in range(3):
            survey = {
                **content, "schema_version": 1, "owner_id": user["_id"],
                "status": "draft", "draft_revision": 1, "share_code": secrets.token_urlsafe(9),
                "created_at": now, "updated_at": now, "published_at": None, "closed_at": None,
            }
            try:
                request.app.state.db.surveys.insert_one(survey)
                return serialize_survey(survey)
            except DuplicateKeyError:
                continue
        raise HTTPException(503, "访问码生成失败，请重试")

    @application.get("/api/surveys/{survey_id}")
    def get_survey(survey_id: str, request: Request, user=Depends(current_user)):
        return serialize_survey(owned_survey(request.app.state.db, survey_id, user["_id"]))

    @application.put("/api/surveys/{survey_id}")
    def save_survey(survey_id: str, payload: SurveySave, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        original = owned_survey(db, survey_id, user["_id"])
        content = content_dict(payload)
        validate_content(content)
        validate_sources(db, content, user["_id"], original)
        saved = db.surveys.find_one_and_update(
            {"_id": original["_id"], "owner_id": user["_id"], "status": "draft", "draft_revision": payload.draft_revision},
            {"$set": {**content, "updated_at": utcnow()}, "$inc": {"draft_revision": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if not saved:
            raise HTTPException(409, "问卷已发布或已被其他页面修改，请重新打开后再操作")
        return serialize_survey(saved)

    @application.post("/api/surveys/{survey_id}/publish")
    def publish_survey(survey_id: str, payload: RevisionRequest, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        survey = owned_survey(db, survey_id, user["_id"])
        if survey["status"] != "draft" or survey["draft_revision"] != payload.draft_revision:
            raise HTTPException(409, "问卷状态或版本已变化，请重新打开")
        validate_content(survey, publishing=True)
        now = utcnow()
        published = db.surveys.find_one_and_update(
            {"_id": survey["_id"], "owner_id": user["_id"], "status": "draft", "draft_revision": payload.draft_revision},
            {"$set": {"status": "published", "published_at": now, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not published:
            raise HTTPException(409, "发布期间问卷被修改，请重新打开后再发布")
        return serialize_survey(published)

    @application.post("/api/surveys/{survey_id}/close")
    def close_survey(survey_id: str, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        original = owned_survey(db, survey_id, user["_id"])
        if original["status"] == "closed":
            return serialize_survey(original)
        now = utcnow()
        closed = db.surveys.find_one_and_update(
            {"_id": original["_id"], "owner_id": user["_id"], "status": "published"},
            {"$set": {"status": "closed", "closed_at": now, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not closed:
            raise HTTPException(409, "只有已发布问卷可以关闭")
        return serialize_survey(closed)

    @application.patch("/api/surveys/{survey_id}/deadline")
    def update_deadline(survey_id: str, payload: DeadlineRequest, request: Request, user=Depends(current_user)):
        db = request.app.state.db
        original = owned_survey(db, survey_id, user["_id"])
        deadline = payload.expires_at
        if deadline is not None:
            deadline = deadline.astimezone(timezone.utc)
            if deadline <= utcnow():
                raise HTTPException(422, "新的截止时间必须晚于当前时间")
        saved = db.surveys.find_one_and_update(
            {"_id": original["_id"], "owner_id": user["_id"], "status": "published"},
            {"$set": {"settings.expires_at": deadline, "updated_at": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if not saved:
            raise HTTPException(409, "只有已发布问卷可以调整截止时间")
        return serialize_survey(saved)

    @application.get("/api/public/surveys/{share_code}")
    def published_preview(share_code: str, request: Request, user=Depends(current_user)):
        return public_survey_view(request.app.state.db, share_code, user["_id"])

    application.include_router(answer_router)
    application.include_router(question_router)
    application.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")

    @application.get("/", include_in_schema=False)
    @application.get("/survey/{share_code}", include_in_schema=False)
    def frontend():
        return FileResponse(FRONTEND / "index.html")

    return application


app = create_app()
