"""流式对话 API — 核心 SSE 通道"""

import asyncio
import json
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse
from app.models.schemas import ChatRequest
from app.core.orchestrator import orchestrator
from app.core.sse_manager import sse_manager, sse_generator
from app.db.sqlite_client import db
from app.agents.profiler import profiler_agent
from app.agents.content_gen import content_gen_agent, mindmap_agent, reading_agent
from app.agents.quiz_gen import quiz_gen_agent
from app.agents.code_agent import code_agent
from app.agents.path_planner import path_planner_agent, tutor_agent
from app.agents.evaluator import evaluator_agent

router = APIRouter(prefix="/api", tags=["对话"])


def _assert_session_owner(session_id: str, user_id: str | None):
    """校验会话存在且属于当前登录用户。

    中间件只覆盖 URL 里带 sess_ 的请求，chat/stream 的 session_id 在
    请求体里，必须在这里显式校验，否则可往他人会话写消息、改他人进度。
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录或登录已过期，请重新登录")
    row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    if row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")


# 注册所有智能体到协调器
def _register_agents():
    orchestrator.register_agent("profiler", profiler_agent)
    orchestrator.register_agent("content_gen", content_gen_agent)
    orchestrator.register_agent("mindmap_gen", mindmap_agent)
    orchestrator.register_agent("reading_gen", reading_agent)
    orchestrator.register_agent("quiz_gen", quiz_gen_agent)
    orchestrator.register_agent("code_agent", code_agent)
    orchestrator.register_agent("path_planner", path_planner_agent)
    orchestrator.register_agent("tutor", tutor_agent)
    orchestrator.register_agent("evaluator", evaluator_agent)


_register_agents()


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """
    统一流式对话入口。
    协调智能体根据意图分发到子智能体，通过 SSE 推送结果。
    """
    _assert_session_owner(req.session_id, getattr(request.state, "user_id", None))

    conn_id, queue = sse_manager.create_connection()

    # 后台处理消息
    asyncio.create_task(
        orchestrator.handle_message(conn_id, req.session_id, req.message, req.context or {})
    )

    return StreamingResponse(
        sse_generator(conn_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/chat/history/{session_id}")
def get_chat_history(session_id: str, request: Request):
    """加载会话的聊天记录和资源"""
    _assert_session_owner(session_id, getattr(request.state, "user_id", None))

    # 加载对话历史
    messages_rows = db.fetch_all(
        """SELECT role, content, created_at FROM chat_messages
           WHERE session_id = ? ORDER BY created_at ASC""",
        (session_id,)
    )
    messages = []
    for r in (messages_rows or []):
        messages.append({
            "role": r["role"],
            "content": r["content"],
            "created_at": r["created_at"],
        })

    # 加载生成的资源
    resources_rows = db.fetch_all(
        """SELECT id, type, title, topic, content, metadata_json, created_at
           FROM resources WHERE session_id = ? ORDER BY created_at DESC""",
        (session_id,)
    )
    resources = []
    for r in (resources_rows or []):
        # 把资源关联到对应的 AI 回复消息
        try:
            meta = json.loads(r["metadata_json"] or "{}")
        except Exception:
            meta = {}
        resources.append({
            "id": r["id"],
            "type": r["type"],
            "title": r["title"],
            "topic": r["topic"],
            "content": r["content"],
            "metadata": meta,
            "created_at": r["created_at"],
        })

    return {"messages": messages, "resources": resources}
