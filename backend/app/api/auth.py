"""用户认证 API — 注册/登录"""

import uuid
import hashlib
import hmac
import secrets
from datetime import datetime
from fastapi import APIRouter, Header, HTTPException
from app.db.sqlite_client import db
from app.core.token_utils import create_token, verify_token
from app.models.schemas import RegisterRequest, LoginRequest, AuthResponse

router = APIRouter(prefix="/api/auth", tags=["用户认证"])


def _hash_password(password: str, salt: str = "") -> str:
    """密码哈希（salt + sha256）"""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """验证密码"""
    try:
        salt, _ = stored.split("$", 1)
        new_hash = _hash_password(password, salt)
        return hmac.compare_digest(stored, new_hash)
    except Exception:
        return False


@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest):
    """用户注册"""
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")

    existing = db.fetch_one("SELECT id FROM users WHERE username = ?", (req.username,))
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    password_hash = _hash_password(req.password)
    display_name = req.display_name or req.username

    db.execute(
        "INSERT INTO users (id, username, password_hash, display_name, last_login) VALUES (?, ?, ?, ?, ?)",
        (user_id, req.username, password_hash, display_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )

    return AuthResponse(
        user_id=user_id,
        username=req.username,
        display_name=display_name,
        token=create_token(user_id),
    )


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest):
    """用户登录"""
    user = db.fetch_one("SELECT id, username, password_hash, display_name FROM users WHERE username = ?", (req.username,))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not _verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="密码错误")

    db.execute(
        "UPDATE users SET last_login = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["id"])
    )

    return AuthResponse(
        user_id=user["id"],
        username=user["username"],
        display_name=user["display_name"] or "",
        token=create_token(user["id"]),
    )


@router.get("/verify")
def verify(authorization: str = Header(default="")):
    """校验 token 是否有效（前端启动时可调用来恢复登录态）"""
    token = authorization.replace("Bearer ", "").strip() if authorization else ""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    user = db.fetch_one("SELECT id, username, display_name FROM users WHERE id = ?", (user_id,))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return {"valid": True, "user_id": user["id"], "username": user["username"],
            "display_name": user["display_name"] or ""}
