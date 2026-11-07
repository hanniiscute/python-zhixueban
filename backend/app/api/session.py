"""会话管理 API — v2"""

import uuid
from fastapi import APIRouter, HTTPException, Request
from app.db.sqlite_client import db
from app.models.schemas import CreateSessionRequest, CreateSessionResponse, SessionInfo

router = APIRouter(prefix="/api", tags=["会话管理"])


@router.post("/session", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest, request: Request):
    """创建或复用学习会话（同一用户+同一课程复用旧会话，保留历史数据）

    安全说明：user_id 一律以登录 token 为准。请求体里传的 user_id 会被忽略，
    否则登录用户可以冒充他人身份创建会话。
    """
    # 中间件已校验签名 token，并把真实用户 ID 写进 request.state
    token_user_id = getattr(request.state, "user_id", None)
    if token_user_id:
        req.user_id = token_user_id

    if not req.user_id:
        raise HTTPException(status_code=400, detail="缺少 user_id，请先登录或注册")

    user = db.fetch_one("SELECT id, display_name FROM users WHERE id = ?", (req.user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在，请先注册")

    # 检查是否已有该用户该课程的会话 → 复用
    existing = db.fetch_one(
        "SELECT id FROM sessions WHERE user_id = ? AND course = ? ORDER BY updated_at DESC LIMIT 1",
        (req.user_id, req.course)
    )
    if existing:
        # 更新活跃时间
        db.execute("UPDATE sessions SET updated_at = NOW() WHERE id = ?", (existing["id"],))
        display_name = user["display_name"] or "同学"
        return CreateSessionResponse(
            session_id=existing["id"],
            greeting=f"欢迎回来{display_name}！👋\n\n继续你的**{req.course}**学习之旅吧~"
        )

    # 全新会话
    session_id = f"sess_{uuid.uuid4().hex[:12]}"

    db.execute(
        """INSERT INTO sessions (id, user_id, course) VALUES (?, ?, ?)""",
        (session_id, req.user_id, req.course)
    )

    display_name = user["display_name"] or "同学"
    greeting = (
        f"你好{display_name}！👋\n\n"
        f"我是你的**{req.course}**学习助手。\n\n"
        "在开始学习之前，我想先了解你的情况。你可以告诉我：\n"
        "- 你之前有编程基础吗？\n"
        "- 学习Python想实现什么目标？\n"
        "- 每天大概能花多长时间学习？\n\n"
        "这样我可以为你定制最合适的学习方案！"
    )

    return CreateSessionResponse(session_id=session_id, greeting=greeting)


@router.get("/session/{session_id}", response_model=SessionInfo)
def get_session(session_id: str):
    """获取会话信息"""
    row = db.fetch_one(
        "SELECT s.id, s.user_id, s.course, s.updated_at, u.display_name "
        "FROM sessions s LEFT JOIN users u ON s.user_id = u.id "
        "WHERE s.id = ?",
        (session_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")

    profile_rows = db.fetch_all(
        "SELECT dimension, field, value, confidence FROM profiles WHERE user_id = ?",
        (row["user_id"],)
    )
    profile_summary = {}
    for p in profile_rows:
        dim = p["dimension"]
        if dim not in profile_summary:
            profile_summary[dim] = {}
        profile_summary[dim][p["field"]] = p["value"]

    return SessionInfo(
        session_id=row["id"],
        user_name=row["display_name"] or "",
        profile_summary=profile_summary,
        last_active=row["updated_at"] or "",
    )
