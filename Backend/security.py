"""Argon2 密码哈希与 MongoDB 登录会话。"""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError
from fastapi import HTTPException, Request, Response


COOKIE_NAME = "survey_session"
SESSION_SECONDS = 12 * 60 * 60
password_hasher = PasswordHasher()
# 不存在的用户也进行一次哈希校验，统一登录失败行为。
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(24))


def utcnow():
    return datetime.now(timezone.utc)


def normalize_username(username: str) -> tuple[str, str]:
    display = unicodedata.normalize("NFKC", username.strip())
    if not display or len(display) > 64 or any(unicodedata.category(c).startswith("C") for c in display):
        raise HTTPException(422, "用户名需为 1～64 个可见字符")
    return display, display.casefold()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(request: Request, response: Response, user_id) -> None:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    request.app.state.db.sessions.insert_one({
        "schema_version": 1,
        "token_hash": token_hash(token),
        "user_id": user_id,
        "created_at": now,
        "expires_at": now + timedelta(seconds=SESSION_SECONDS),
    })
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
        secure=request.app.state.cookie_secure, samesite="lax", path="/",
    )


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "请先登录")
    db = request.app.state.db
    session = db.sessions.find_one({"token_hash": token_hash(token), "expires_at": {"$gt": utcnow()}})
    user = db.users.find_one({"_id": session["user_id"]}) if session else None
    if not user:
        raise HTTPException(401, "登录已失效，请重新登录")
    return user


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerificationError, InvalidHash):
        return False


def public_user(user: dict) -> dict:
    return {"id": str(user["_id"]), "username": user["username"], "created_at": user["created_at"]}
