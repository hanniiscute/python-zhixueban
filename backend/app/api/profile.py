"""画像 API"""

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.db.sqlite_client import db
from app.core import profile_utils
from app.models.profile import (
    StudentProfile, ProfileResponse, KnowledgeBase, LearningStyle,
    ErrorPatterns, CognitiveLevel, InterestTendency, LearningPace, LearningGoal,
    ProfileHistoryItem, KeyExchange, ErrorPattern
)

router = APIRouter(prefix="/api", tags=["学生画像"])


def _parse_list_value(value: str) -> list[str]:
    """还原画像中的多值字段。

    画像表的查询按 (dimension, field) 取 MAX(id)，每个字段只保留一行，
    因此列表类字段（known_concepts / directions / error_prone_topics 等）
    以 JSON 数组的形式存这一行。这里把它拆回多个元素；
    问卷等来源写入的是普通字符串，按单元素处理。
    """
    if not value:
        return []
    s = str(value).strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [str(value)]


# ── 问卷：问题 → 画像维度映射 ──
QUESTION_MAP = {
    "programming_level": ("knowledge_base", "level", {
        "zero": "零基础", "little": "了解一点", "some": "有基础", "proficient": "比较熟练",
    }),
    "learning_style": ("learning_style", "type", {
        "video": "视频学习型", "reading": "阅读文档型", "project": "动手项目型", "practice": "刷题练习型",
    }),
    "learning_goal": ("learning_goal", "primary", {
        "exam": "通过考试", "job": "找工作/面试", "personal": "做个人项目", "upskill": "提升技能", "research": "学术研究",
    }),
    "interest_area": ("interest_tendency", "directions", {
        "data_ai": "数据分析/AI", "web": "Web开发", "game": "游戏开发", "automation": "自动化脚本", "algorithm": "算法",
    }),
    "thinking_style": ("cognitive_level", "thinking_style", {
        "memorize": "先记住再说", "understand": "理解原理再动手", "try": "直接上手试一试", "compare": "对比不同方案",
    }),
    "daily_hours": ("learning_pace", "daily_available_hours", {
        "<30min": "少于30分钟", "30min-1h": "30分钟-1小时", "1-2h": "1-2小时", ">2h": "2小时以上",
    }),
}


class QuestionnaireRequest(BaseModel):
    user_id: str
    session_id: str
    answers: dict  # { question_key: value }


class QuestionnaireResponse(BaseModel):
    saved: bool = True
    dimensions_filled: list[str] = []


def _get_user_id_by_session(session_id: str) -> str:
    """通过 session_id 查询 user_id"""
    row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row["user_id"]


def _compute_learning_pace(profile: StudentProfile, user_id: str):
    """从真实 learning_records 计算学习节奏数据"""
    from datetime import date, timedelta

    # 获取该用户所有 session 的学习记录
    records = db.fetch_all(
        """SELECT lr.time_spent_minutes, lr.self_evaluation, DATE(lr.created_at) AS learn_date
           FROM learning_records lr
           JOIN sessions s ON lr.session_id = s.id
           WHERE s.user_id = ?""",
        (user_id,)
    )

    if not records:
        return

    # 1. 平均学习时长
    total_min = sum(r["time_spent_minutes"] or 0 for r in records)
    session_dates = set()
    for r in records:
        d = r["learn_date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        session_dates.add(d)

    # avg_session_minutes: 按天平均
    profile.learning_pace.avg_session_minutes = max(1, total_min // max(1, len(session_dates)))

    # 2. 连续学习天数
    today = date.today()
    streak = 0
    for i in range(365):
        check = today - timedelta(days=i)
        if check in session_dates:
            streak += 1
        else:
            break
    profile.learning_pace.streak_days = streak

    # 3. 完成速度判定：已完成主题数 ÷ 活跃学习天数
    #
    #    刻意不用「主题数 ÷ 学习时长」：learning_records.time_spent_minutes 由各入口
    #    写死成常数（实测 43/47 条都是 5 分钟），拿它当分母对所有用户结果雷同、
    #    没有区分度，还会把"学得快"这种结论建立在假数据上。
    #    活跃天数只依赖"哪天学过"这一事实，可靠得多。
    # 从学习路径统计已完成 topic 数
    path_rows = db.fetch_all(
        """SELECT lp.path_json FROM learning_paths lp
           JOIN sessions s ON lp.session_id = s.id
           WHERE s.user_id = ?""",
        (user_id,)
    )
    completed = 0
    import json
    for pr in path_rows:
        try:
            data = json.loads(pr["path_json"] or "{}")
        except json.JSONDecodeError:
            continue
        for phase in data.get("phases", []):
            for topic in phase.get("topics", []):
                if topic.get("status") == "completed":
                    completed += 1

    active_days = len(session_dates)
    if completed > 0 and active_days > 0:
        per_day = completed / active_days
        if per_day >= 1.5:
            profile.learning_pace.completion_speed = "快"
        elif per_day >= 0.7:
            profile.learning_pace.completion_speed = "中等"
        else:
            profile.learning_pace.completion_speed = "慢"


def _build_profile(user_id: str) -> StudentProfile:
    """从数据库构建画像对象（按 user_id 查询，去重取最新）"""
    rows = db.fetch_all(
        """SELECT dimension, field, value, confidence, evidence FROM profiles
           WHERE user_id = ?
             AND id IN (
               SELECT MAX(id) FROM profiles WHERE user_id = ? GROUP BY dimension, field
             )""",
        (user_id, user_id)
    )

    profile = StudentProfile()

    for r in rows:
        dim = r["dimension"]
        field = r["field"]
        value = r["value"]
        conf = r["confidence"]
        evd = r["evidence"]

        if dim == "knowledge_base":
            if field == "level":
                profile.knowledge_base.level = value
            elif field == "known_concepts":
                profile.knowledge_base.known_concepts.extend(_parse_list_value(value))
            elif field == "unknown_concepts":
                profile.knowledge_base.unknown_concepts.extend(_parse_list_value(value))
        elif dim == "learning_style":
            if field == "type":
                profile.learning_style.type = value
            elif field == "preferred_formats":
                profile.learning_style.preferred_formats.extend(_parse_list_value(value))
        elif dim == "error_patterns":
            if field == "error_prone_topics":
                profile.error_patterns.error_prone_topics.extend(_parse_list_value(value))
            elif field == "mistake":
                profile.error_patterns.common_mistakes.append(
                    ErrorPattern(type=value, detail=evd, frequency=1)
                )
        elif dim == "cognitive_level":
            if field == "thinking_style":
                profile.cognitive_level.thinking_style = value
            elif hasattr(profile.cognitive_level, field):
                try:
                    setattr(profile.cognitive_level, field, int(value))
                except ValueError:
                    pass
        elif dim == "interest_tendency":
            if field == "directions":
                profile.interest_tendency.directions.extend(_parse_list_value(value))
            elif field == "engagement_topics":
                profile.interest_tendency.engagement_topics.extend(_parse_list_value(value))
        elif dim == "learning_pace":
            if field == "completion_speed":
                profile.learning_pace.completion_speed = value
            elif field == "daily_available_hours":
                profile.learning_pace.daily_available_hours = value
            elif field == "avg_session_minutes":
                profile.learning_pace.avg_session_minutes = int(value)
            elif field == "peak_hours":
                profile.learning_pace.peak_hours.extend(_parse_list_value(value))
        elif dim == "learning_goal":
            if field == "primary":
                profile.learning_goal.primary = value
            elif field == "secondary":
                profile.learning_goal.secondary = value
            elif field == "timeline":
                profile.learning_goal.timeline = value

    # ── 从真实学习记录计算学习节奏（覆盖 profiles 表中的静态值）──
    _compute_learning_pace(profile, user_id)

    # ── 认知水平未评估时，根据知识等级推导合理默认值 ──
    cl = profile.cognitive_level
    if cl.remember + cl.understand + cl.apply + cl.analyze + cl.evaluate + cl.create == 0:
        level = profile.knowledge_base.level or "未知"
        defaults = {
            "零基础":   [30, 20, 10,  5,  5,  5],
            "了解一点": [50, 40, 25, 15, 10, 10],
            "有一点基础": [70, 60, 45, 30, 20, 15],
            "有基础":   [85, 75, 60, 45, 35, 25],
            "比较熟练": [90, 85, 75, 60, 50, 40],
            "入门":     [40, 30, 20, 10,  5,  5],
            "进阶":     [75, 65, 50, 40, 30, 20],
            "熟练":     [90, 88, 80, 70, 60, 50],
        }
        vals = defaults.get(level, [15, 10, 5, 5, 5, 5])
        # 用 model_copy 确保 Pydantic v2 正确更新
        from app.models.profile import CognitiveLevel
        profile.cognitive_level = CognitiveLevel(
            remember=vals[0], understand=vals[1], apply=vals[2],
            analyze=vals[3], evaluate=vals[4], create=vals[5],
            thinking_style=cl.thinking_style,
        )

    return profile


@router.get("/profile/{session_id}", response_model=ProfileResponse)
def get_profile(session_id: str):
    """获取当前画像 v2"""
    user_id = _get_user_id_by_session(session_id)

    profile = _build_profile(user_id)

    # ── 认知水平未评估时，根据知识等级推导默认值 ──
    cl = profile.cognitive_level
    total = cl.remember + cl.understand + cl.apply + cl.analyze + cl.evaluate + cl.create
    if total == 0:
        level = profile.knowledge_base.level or "未知"
        defaults = {
            "零基础":   [30, 20, 10,  5,  5,  5],
            "了解一点": [50, 40, 25, 15, 10, 10],
            "有一点基础": [70, 60, 45, 30, 20, 15],
            "有基础":   [85, 75, 60, 45, 35, 25],
            "比较熟练": [90, 85, 75, 60, 50, 40],
        }
        vals = defaults.get(level, [15, 10, 5, 5, 5, 5])
        profile.cognitive_level = CognitiveLevel(
            remember=vals[0], understand=vals[1], apply=vals[2],
            analyze=vals[3], evaluate=vals[4], create=vals[5],
            thinking_style=cl.thinking_style,
        )

    rows = db.fetch_all("SELECT confidence FROM profiles WHERE user_id = ?", (user_id,))
    avg_confidence = sum(r["confidence"] for r in rows) / len(rows) if rows else 0.0

    last_updated = db.fetch_one(
        "SELECT created_at as updated_at FROM profiles WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    )

    return ProfileResponse(
        profile=profile,
        last_updated=last_updated["updated_at"] if last_updated else "",
        confidence=round(avg_confidence, 2),
    )


@router.get("/profile/{session_id}/history")
def get_profile_history(session_id: str, dimension: str = "knowledge_base"):
    """获取画像维度历史"""
    user_id = _get_user_id_by_session(session_id)

    rows = db.fetch_all(
        """SELECT dimension, field, value, confidence, created_at
           FROM profiles
           WHERE user_id = ? AND dimension = ?
           ORDER BY created_at ASC""",
        (user_id, dimension)
    )

    history = []
    for r in rows:
        history.append({
            "time": r["created_at"],
            "field": r["field"],
            "value": r["value"],
            "confidence": r["confidence"],
        })

    return {"dimension": dimension, "history": history}


@router.get("/profile/{session_id}/conversation-summary")
def get_conversation_summary(session_id: str):
    """获取画像构建的关键对话摘要"""
    user_id = _get_user_id_by_session(session_id)

    rows = db.fetch_all(
        "SELECT dimension, field, value, evidence FROM profiles WHERE user_id = ? AND evidence != ''",
        (user_id,)
    )

    exchanges = []
    for i, r in enumerate(rows):
        exchanges.append({
            "round_num": i + 1,
            "user_said": r["evidence"],
            "system_extracted": f"{r['dimension']}.{r['field']}: {r['value']}",
            "dimension_affected": r["dimension"],
        })

    return {"key_exchanges": exchanges}


@router.post("/profile/questionnaire", response_model=QuestionnaireResponse)
def save_questionnaire(req: QuestionnaireRequest, request: Request):
    """保存入门问卷答案，构建初始画像

    安全说明：user_id 一律以登录 token 为准，请求体里的会被忽略，
    否则登录用户可以往别人画像里写数据。
    """
    token_user_id = getattr(request.state, "user_id", None)
    if token_user_id:
        req.user_id = token_user_id
    if not req.user_id:
        raise HTTPException(status_code=400, detail="缺少 user_id，请先登录")
    dimensions_filled = []

    for qkey, value in req.answers.items():
        mapping = QUESTION_MAP.get(qkey)
        if not mapping:
            continue
        dimension, field, labels = mapping
        label = labels.get(value, value)

        # profiles 有 UNIQUE(user_id,dimension,field) 约束，必须 upsert，
        # 否则问卷重做一次就会撞唯一键导致接口 500。
        profile_utils.upsert(
            req.user_id, req.session_id, dimension, field,
            label, 0.85, f"入门问卷: {qkey}",
        )
        if dimension not in dimensions_filled:
            dimensions_filled.append(dimension)

    return QuestionnaireResponse(
        saved=True,
        dimensions_filled=dimensions_filled,
    )
