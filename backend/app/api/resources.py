"""资源管理 API"""

import json
from fastapi import APIRouter, HTTPException
from app.db.sqlite_client import db
from app.core import profile_utils
from app.models.resource import (
    ResourceItem, ResourceListResponse, ResourceDetail,
    ResourceMeta, ResourceFeedbackRequest
)

router = APIRouter(prefix="/api", tags=["学习资源"])

# 标题里由生成器拼上的后缀，展示时去掉（"字符串操作 - 学习文档" → "字符串操作"）
_TITLE_SUFFIXES = ("- 学习文档", "— 学习文档", "· 学习文档", "学习文档",
                   "思维导图", "拓展阅读", "练习题", "分层练习题")
# 明显是"聊天原话"而不是主题名的特征（历史脏数据）
_QUESTION_MARKS = ("？", "?", "吗", "呢", "怎么", "如何", "为什么")


# 资源类型中文名（同一主题可能有讲义+练习题两种资料，用它区分）
_TYPE_LABELS = {
    "document": "讲义",
    "reading": "拓展阅读",
    "mindmap": "思维导图",
    "quiz": "练习题",
    "notebook": "代码实操",
}


def _clean_title(raw: str, topic: str) -> str:
    """把历史脏标题收拾成能看的名字：优先用主题名，去掉生成器后缀"""
    base = (topic or "").strip() or (raw or "").strip()
    for suf in _TITLE_SUFFIXES:
        if base.endswith(suf):
            base = base[: -len(suf)].strip(" -—·")
            break
    # 主题名本身是问句（用户原话）或过长，截断保留可读部分
    if len(base) > 18 or any(m in base for m in _QUESTION_MARKS):
        base = base[:18].rstrip("，,。的了吗呢") + "…"
    return base or "学习资料"


def _completed_topics(session_id: str) -> set:
    """该会话已学完的主题集合（学习路径 JSON + 学习记录 topic）"""
    done = set()

    path_row = db.fetch_one(
        "SELECT path_json FROM learning_paths WHERE session_id = ?", (session_id,)
    )
    if path_row and path_row["path_json"]:
        try:
            path_data = json.loads(path_row["path_json"] or "{}")
            for phase in path_data.get("phases", []):
                for t in phase.get("topics", []):
                    if t.get("status") == "completed":
                        title = (t.get("title") or "").strip()
                        if title:
                            done.add(title)
                if phase.get("status") == "completed" and phase.get("title"):
                    done.add(phase["title"].strip())
        except Exception:
            pass

    rows = db.fetch_all(
        "SELECT DISTINCT topic FROM learning_records WHERE session_id = ?", (session_id,)
    )
    for r in rows:
        if r["topic"]:
            done.add(r["topic"].strip())

    return done


@router.get("/resources/{session_id}")
def list_resources(
    session_id: str,
    type: str = "",
    topic: str = "",
    page: int = 1,
    size: int = 50
):
    """获取已生成资源列表（同主题同类型只保留最新一份，并标记是否已学完）"""
    where_clauses = ["session_id = ?"]
    params = [session_id]

    if type:
        where_clauses.append("type = ?")
        params.append(type)
    if topic:
        where_clauses.append("topic LIKE ?")
        params.append(f"%{topic}%")

    where_sql = " AND ".join(where_clauses)

    # 取该会话全部匹配资源（按时间倒序），在内存里去重——单会话数据量很小
    rows = db.fetch_all(
        f"""SELECT id, type, title, topic, metadata_json, user_rating, created_at
            FROM resources
            WHERE {where_sql}
            ORDER BY created_at DESC, id DESC""",
        tuple(params)
    )

    done_topics = _completed_topics(session_id)

    seen = set()
    deduped = []
    merged = 0
    for r in rows:
        raw_topic = (r["topic"] or "").strip()
        key = (raw_topic or (r["title"] or "").strip(), r["type"])
        if key in seen:
            merged += 1
            continue
        seen.add(key)
        deduped.append(r)

    total = len(deduped)
    offset = (page - 1) * size
    page_rows = deduped[offset: offset + size]

    resources = []
    for r in page_rows:
        meta = json.loads(r["metadata_json"] or "{}")
        raw_topic = (r["topic"] or "").strip()
        resources.append(ResourceItem(
            resource_id=r["id"],
            type=r["type"],
            title=_clean_title(r["title"], raw_topic),
            topic=raw_topic,
            generated_by=meta.get("generated_by", "content_gen"),
            created_at=r["created_at"] or "",
            metadata=ResourceMeta(**meta) if meta else ResourceMeta(),
            user_rating=r["user_rating"] or 0.0,
            learned=bool(raw_topic) and raw_topic in done_topics,
            type_label=_TYPE_LABELS.get(r["type"], "资料"),
        ))

    return ResourceListResponse(
        total=total, page=page, resources=resources, duplicates_merged=merged
    )


@router.get("/resources/{session_id}/{resource_id}")
def get_resource(session_id: str, resource_id: str):
    """获取单个资源详情"""
    row = db.fetch_one(
        "SELECT * FROM resources WHERE id = ? AND session_id = ?",
        (resource_id, session_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="资源不存在")

    meta = json.loads(row["metadata_json"] or "{}")

    return ResourceDetail(
        resource_id=row["id"],
        type=row["type"],
        title=row["title"],
        content=row["content"] or "",
        topic=row["topic"] or "",
        difficulty=meta.get("difficulty", "入门"),
        prerequisites=meta.get("prerequisites", []),
        references=meta.get("references", []),
        related_resources=meta.get("related_resources", []),
        created_at=row["created_at"] or "",
    )


@router.post("/resources/{session_id}/{resource_id}/feedback")
def submit_feedback(session_id: str, resource_id: str, req: ResourceFeedbackRequest):
    """提交资源反馈"""
    row = db.fetch_one(
        "SELECT id FROM resources WHERE id = ? AND session_id = ?",
        (resource_id, session_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="资源不存在")

    # 更新评分
    db.execute(
        "UPDATE resources SET user_rating = ? WHERE id = ?",
        (req.rating, resource_id)
    )

    # 如果反馈难度不匹配，更新画像
    if req.difficulty_feedback in ("太难", "太简单"):
        session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
        user_id = session_row["user_id"] if session_row else None
        if user_id:
            # profiles 有 UNIQUE(user_id,dimension,field) 约束，必须 upsert，
            # 否则同一用户对第二份资源反馈难度就会撞唯一键导致接口 500。
            profile_utils.upsert(
                user_id, session_id, "learning_style", "difficulty_preference",
                req.difficulty_feedback, 0.7, req.comment or "",
            )

    return {
        "received": True,
        "profile_updated_dimensions": ["learning_style"] if req.difficulty_feedback in ("太难", "太简单") else []
    }
