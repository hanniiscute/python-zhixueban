"""学习路径 API — 基于 trea 知识库 + 学生画像的个性化路径"""

import json
import os
import uuid
from fastapi import APIRouter, HTTPException
from app.db.sqlite_client import db
from app.core import profile_utils
from app.core import vocab
from app.models.learning_path import (
    LearningPathResponse, RecommendationsResponse,
    RecommendationItem, CompleteTopicRequest, StartTopicRequest,
    StartPracticeRequest, SubmitPracticeRequest,
)
from config.settings import KNOWLEDGE_DATA_DIR

router = APIRouter(prefix="/api", tags=["学习路径"])

# ── 兴趣方向 → trea 路径 / 编程基础 → 起点策略 ──
# 统一由 app.core.vocab 提供（历史上这里用的是英文 key，与问卷写入的中文标签
# 对不上，导致所有人方向路径都退化成默认 path_2）。
INTEREST_TO_PATHS = vocab.INTEREST_TO_PATHS
LEVEL_STRATEGY = vocab.LEVEL_TO_STRATEGY


def _load_trea_data() -> list[dict]:
    """加载 trea 学习路径数据"""
    path_file = os.path.join(KNOWLEDGE_DATA_DIR, "learning_paths.json")
    try:
        with open(path_file, "r", encoding="utf-8") as f:
            return json.load(f).get("learning_paths", [])
    except Exception:
        return []


def _get_user_profile(user_id: str) -> dict:
    """读取用户画像，转为扁平 dict"""
    rows = db.fetch_all(
        "SELECT dimension, field, value FROM profiles WHERE user_id = ?", (user_id,)
    )
    p = {}
    for r in rows:
        p.setdefault(r["dimension"], {})[r["field"]] = r["value"]
    return p


def _build_personalized_phases(session_id: str) -> dict:
    """根据学生画像生成个性化学习路径 phases

    Returns:
        {"path_id": "...", "phases": [...], "recommended_next": {...}}
    """
    # 1. 查用户
    session = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    user_id = session["user_id"] if session else None

    # 2. 读画像
    profile = _get_user_profile(user_id) if user_id else {}
    raw_level = profile.get("knowledge_base", {}).get("level", "零基础")
    raw_interest = profile.get("interest_tendency", {}).get("directions", "")

    # 3. 归一化（问卷写中文标签、对话画像写 入门/进阶/熟练，词表不统一时这里全部落空）
    level = vocab.normalize_level(raw_level)
    interest_key = vocab.normalize_interest(raw_interest)
    strategy = vocab.level_to_strategy(level)

    # 4. 加载 trea 数据
    all_paths = _load_trea_data()
    path_map = {lp["path_id"]: lp for lp in all_paths}
    path_1 = path_map.get("path_1")

    # 5. 选定兴趣方向路径
    target_path_ids = vocab.interest_to_paths(raw_interest)
    target_paths = [path_map[pid] for pid in target_path_ids if pid in path_map]
    if not target_paths:
        target_paths = [path_map.get("path_2", all_paths[1]) if len(all_paths) > 1 else None]
        target_paths = [p for p in target_paths if p]

    # 6. 构建 phases
    phases = []
    first_topic = None

    if path_1 and strategy["mode"] != "skip":
        # path_1 始终作为第一阶段
        nodes = path_1.get("nodes", [])
        unlock_n = strategy["unlock_count"]
        topics = []
        for j, node in enumerate(nodes):
            status = "available" if j < unlock_n else "locked"
            if status == "available" and first_topic is None:
                first_topic = node
            topics.append({
                "topic_id": node["id"],
                "title": node["name"],
                "status": status,
                "estimated_hours": node.get("estimated_hours", 0),
                "difficulty": node.get("difficulty", ""),
                "chapter": node.get("chapter", ""),
            })
        phases.append({
            "order": 1,
            "title": path_1.get("path_name", "Python基础语法"),
            "status": "available",
            "progress": 0,
            "estimated_hours": sum(n.get("estimated_hours", 0) for n in nodes),
            "difficulty": path_1.get("difficulty", "简单"),
            "topics": topics,
        })

    # 7. 兴趣方向路径
    for i, tp in enumerate(target_paths):
        nodes = tp.get("nodes", [])
        is_first_direction = (strategy["mode"] == "skip" and i == 0) or \
                            (strategy["mode"] != "skip" and len(phases) == 1 and i == 0)
        # 严格串行：方向阶段在基础阶段完成前保持锁定。
        # 例外：skip 模式（比较熟练）没有基础阶段，方向一就是起点。
        phase_unlocked = is_first_direction and strategy["mode"] == "skip"
        topics = []
        for j, node in enumerate(nodes):
            status = "available" if (phase_unlocked and j == 0) else "locked"
            if status == "available" and first_topic is None:
                first_topic = node
            topics.append({
                "topic_id": node["id"],
                "title": node["name"],
                "status": status,
                "estimated_hours": node.get("estimated_hours", 0),
                "difficulty": node.get("difficulty", ""),
                "chapter": node.get("chapter", ""),
            })
        phases.append({
            "order": len(phases) + 1,
            "title": tp.get("path_name", f"方向{i+1}"),
            "status": "available" if phase_unlocked else "locked",
            "progress": 0,
            "estimated_hours": sum(n.get("estimated_hours", 0) for n in nodes),
            "difficulty": tp.get("difficulty", "中等"),
            "topics": topics,
        })

    # 8. 推荐下一步
    rec = {}
    if first_topic:
        rec = {"topic": first_topic["name"],
               "reason": f"根据你的基础（{level}）和兴趣（{raw_interest or '未指定'}），从这里开始最合适"}

    return {
        "phases": phases,
        "recommended_next": rec,
    }


def _enforce_serial_unlock(path_data: dict):
    """严格串行解锁约束（幂等）：基础阶段未全部完成前，方向阶段不允许有 available 主题。

    旧版本生成的路径会把方向一第一个主题提前解锁，这里在加载时纠正：
    只把 available 降为 locked，in_progress/completed 不动（已开始的让它学完）。
    基础阶段全部完成后本函数为空操作。skip 模式（没有基础阶段）不受影响。
    """
    phases = path_data.get("phases", [])
    basics = None
    for p in phases:
        if not (p.get("title") or "").startswith("方向"):
            basics = p
            break
    if basics is None or basics.get("status") == "completed":
        return
    for p in phases:
        if (p.get("title") or "").startswith("方向"):
            changed = False
            for t in p.get("topics", []):
                if t.get("status") == "available":
                    t["status"] = "locked"
                    changed = True
            if changed and p.get("status") == "available":
                p["status"] = "locked"


def _get_or_create_path(session_id: str) -> dict:
    """获取已有路径，不存在则生成个性化路径并保存"""
    row = db.fetch_one(
        "SELECT id, path_json FROM learning_paths WHERE session_id = ?", (session_id,)
    )
    if row:
        data = json.loads(row["path_json"] or "{}")
        if data.get("phases"):
            _enforce_serial_unlock(data)
            return {"path_id": row["id"], **data}

    # 生成个性化路径
    path_data = _build_personalized_phases(session_id)

    # 保存到 DB
    import uuid
    path_id = f"path_{uuid.uuid4().hex[:8]}"
    try:
        db.execute(
            """INSERT INTO learning_paths (id, session_id, path_json)
               VALUES (?, ?, ?)""",
            (path_id, session_id, json.dumps(path_data, ensure_ascii=False))
        )
    except Exception:
        pass  # 唯一键冲突时忽略

    path_data["path_id"] = path_id
    return path_data


@router.get("/learning-path/{session_id}")
def get_learning_path(session_id: str):
    """获取个性化学习路径"""
    data = _get_or_create_path(session_id)
    return LearningPathResponse(
        path_id=data.get("path_id", ""),
        generated_at="",
        updated_at="",
        phases=data.get("phases", []),
        recommended_next=data.get("recommended_next", {}),
    )


@router.get("/learning-path/{session_id}/recommendations")
def get_recommendations(session_id: str, count: int = 5):
    """获取推荐资源推送"""
    session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if not session_row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="会话不存在")
    user_id = session_row["user_id"]

    # 获取用户画像以做个性化推荐
    profile_rows = db.fetch_all(
        "SELECT dimension, field, value FROM profiles WHERE user_id = ?",
        (user_id,)
    )

    # 获取已有资源
    resources = db.fetch_all(
        "SELECT id, type, title, topic, metadata_json FROM resources WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        (session_id, count)
    )

    recommendations = []
    for i, r in enumerate(resources):
        recommendations.append(RecommendationItem(
            resource_id=r["id"],
            title=r["title"],
            type=r["type"],
            reason=f"基于你的学习进度推荐（匹配度: {0.95 - i * 0.05:.2f}）",
            priority="high" if i == 0 else "medium",
            match_score=round(0.95 - i * 0.05, 2),
        ))

    if not recommendations:
        recommendations.append(RecommendationItem(
            resource_id="",
            title="从变量与赋值开始学习吧！",
            type="document",
            reason="这是Python编程的第一步",
            priority="high",
            match_score=0.99,
        ))

    return RecommendationsResponse(recommendations=recommendations)


# ── 主题完成规则 ──
# 一个主题要「开始学习」+「练练手通过(≥60%)」两步都做了才算完成，先后顺序不限。
# - 开始学习（路径页按钮 / 聊天里说"学完了" / ✅按钮）→ 主题标记 in_progress
# - 练习通过时若已开始 → completed 并解锁下一个
# - 练习通过时还没开始 → 只标记 in_progress，等开始学习时自动补完成
# - 开始学习时发现练习已通过 → 直接补成 completed

def _practice_passed(session_id: str, topic: str) -> bool:
    """该主题是否有过通过的练习记录（learning_records 里 submit_practice 写的'- 通过'）"""
    row = db.fetch_one(
        "SELECT id FROM learning_records WHERE session_id = ? AND topic = ? "
        "AND self_evaluation LIKE ? LIMIT 1",
        (session_id, topic, "%- 通过%"),
    )
    return bool(row)


def _load_path_data(session_id: str) -> tuple[dict, str]:
    """加载（或初始化）路径 JSON，返回 (path_data, path_id)"""
    path_row = db.fetch_one(
        "SELECT id, path_json FROM learning_paths WHERE session_id = ?",
        (session_id,),
    )
    if path_row:
        data = json.loads(path_row["path_json"] or "{}")
        _enforce_serial_unlock(data)
        return data, path_row["id"]
    return _build_personalized_phases(session_id), f"path_{uuid.uuid4().hex[:8]}"


def _save_path_data(session_id: str, path_id: str, path_data: dict):
    db.execute(
        """INSERT INTO learning_paths (id, session_id, path_json)
           VALUES (?, ?, ?)
           ON DUPLICATE KEY UPDATE path_json = VALUES(path_json), updated_at = NOW()""",
        (path_id, session_id, json.dumps(path_data, ensure_ascii=False)),
    )


def _apply_topic_status(phases: list, topic_name: str, new_status: str) -> bool:
    """把匹配的主题设为 new_status（completed 的不回退）。

    返回是否有主题被新标记为 completed（用于判断是否解锁下一个）。
    """
    just_completed = False
    for phase in phases:
        for topic in phase.get("topics", []):
            if topic.get("title") == topic_name or topic.get("topic_id") == topic_name:
                if topic.get("status") == "completed":
                    continue
                topic["status"] = new_status
                if new_status == "completed":
                    just_completed = True
        # 没有子 topic 的 phase，phase 本身就是主题
        if phase.get("title") == topic_name and phase.get("status") != "completed":
            phase["status"] = new_status
            if new_status == "completed":
                just_completed = True
        # 阶段内全部完成 → 阶段完成
        topics = phase.get("topics", [])
        if topics and new_status == "completed" and all(t.get("status") == "completed" for t in topics):
            phase["status"] = "completed"
            phase["progress"] = 1.0
    return just_completed


def _unlock_next_topic(phases: list, topic_name: str):
    """解锁紧随其后的那个 locked 主题。

    若完成的是本阶段最后一个主题，则解锁下一个阶段的第一个主题（严格串行）。
    """
    for pi, phase in enumerate(phases):
        topic_list = phase.get("topics", [])
        for i, topic in enumerate(topic_list):
            if topic.get("title") == topic_name or topic.get("topic_id") == topic_name:
                if i + 1 < len(topic_list):
                    if topic_list[i + 1].get("status") == "locked":
                        topic_list[i + 1]["status"] = "available"
                    return
                # 本阶段最后一个 → 解锁下一个有主题的阶段的第一项
                for next_phase in phases[pi + 1:]:
                    next_topics = next_phase.get("topics") or []
                    if not next_topics:
                        continue
                    if next_topics[0].get("status") == "locked":
                        next_topics[0]["status"] = "available"
                        next_phase["status"] = "available"
                    break
                return


@router.post("/learning-path/{session_id}/start-topic")
def start_topic(session_id: str, req: StartTopicRequest):
    """标记主题为「已开始学习」。

    若该主题此前已通过练练手 → 直接补成 completed 并解锁下一个（顺序无关）。
    """
    session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if not session_row:
        raise HTTPException(status_code=404, detail="会话不存在")

    passed = _practice_passed(session_id, req.topic)
    path_data, path_id = _load_path_data(session_id)
    phases = path_data.get("phases", [])

    completed_now = _apply_topic_status(phases, req.topic, "completed" if passed else "in_progress")
    if completed_now:
        _unlock_next_topic(phases, req.topic)
    _save_path_data(session_id, path_id, path_data)

    return {
        "started": True,
        "completed": passed or completed_now,
        "practice_passed": passed,
    }


@router.post("/learning-path/{session_id}/complete")
def complete_topic(session_id: str, req: CompleteTopicRequest):
    """记录学习行为（聊天说"学完了" / ✅按钮）。

    新规则下这只代表「已开始学习」→ 主题标记 in_progress；
    若练练手已通过则直接补成 completed。
    """
    session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if not session_row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="会话不存在")
    user_id = session_row["user_id"]

    # 记录学习行为
    db.execute(
        """INSERT INTO learning_records (session_id, topic, resource_id, time_spent_minutes, self_evaluation)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, req.topic, req.resource_id, req.time_spent_minutes, req.self_evaluation)
    )

    # 更新画像 — 学习节奏（profiles 有 UNIQUE(user_id,dimension,field) 约束，必须 upsert）
    if req.time_spent_minutes > 0:
        profile_utils.upsert(
            user_id, session_id, "learning_pace", "avg_session_minutes",
            str(req.time_spent_minutes), 0.7, req.topic,
        )

    # 更新画像 — 知识基础（标记已知概念）
    profile_utils.append_list(
        user_id, session_id, "knowledge_base", "known_concepts",
        req.topic, 0.8, f"完成{req.topic}学习",
    )

    passed = _practice_passed(session_id, req.topic)
    path_data, path_id = _load_path_data(session_id)
    phases = path_data.get("phases", [])

    completed_now = _apply_topic_status(phases, req.topic, "completed" if passed else "in_progress")
    if completed_now:
        _unlock_next_topic(phases, req.topic)
    _save_path_data(session_id, path_id, path_data)

    return {
        "path_updated": passed or completed_now,
        "completed": passed or completed_now,
        "practice_passed": passed,
        "new_recommendations": [],
        "profile_updated_dimensions": ["knowledge_base", "learning_pace"],
    }


# ── 练练手（闯关测验）──

@router.post("/learning-path/{session_id}/practice/start")
def start_practice(session_id: str, req: StartPracticeRequest):
    """为指定主题生成练习题

    为提速：默认先复用该主题最近生成过的一套题（毫秒级返回）；
    只有第一次、或前端传 force=true（"换一批"）时才真正调大模型。
    """
    from app.agents.quiz_gen import quiz_gen_agent

    # ── 缓存复用：同主题已有题目直接返回，避免每次都等几十秒 ──
    if not req.force:
        try:
            cached = db.fetch_one(
                """SELECT content FROM resources
                   WHERE session_id = ? AND type = 'quiz' AND topic = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, req.topic),
            )
            if cached and cached.get("content"):
                data = json.loads(cached["content"])
                if data.get("questions"):
                    return data
        except Exception as e:
            print(f"[practice] 缓存读取失败（将重新生成）: {e}")

    try:
        quiz_data = quiz_gen_agent.generate_sync(session_id, req.topic)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"题目生成失败: {str(e)}")

    if not quiz_data.get("questions"):
        raise HTTPException(status_code=500, detail="题目生成失败，请重试")

    return quiz_data


@router.post("/learning-path/{session_id}/practice/submit")
def submit_practice(session_id: str, req: SubmitPracticeRequest):
    """提交练习答案，正确率 ≥ 60% 则标记完成并解锁下一阶段"""
    session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if not session_row:
        raise HTTPException(status_code=404, detail="会话不存在")
    user_id = session_row["user_id"]

    score_pct = round(req.correct / req.total * 100, 1) if req.total > 0 else 0
    passed = score_pct >= 60
    print(f"[practice] 收到提交: topic={req.topic}, score={req.correct}/{req.total}={score_pct}%, passed={passed}")

    # 记录尝试（使用实际耗时，若前端未传则用题目数估算）
    time_spent = req.time_spent_minutes if req.time_spent_minutes > 0 else max(1, req.total * 2)
    db.execute(
        """INSERT INTO learning_records (session_id, topic, resource_id, time_spent_minutes, self_evaluation)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, req.topic, req.resource_id, time_spent,
         f"练习得分: {req.correct}/{req.total} ({score_pct}%) - {'通过' if passed else '未通过'}")
    )

    path_updated = False
    mistakes_saved = 0

    if passed:
        # 更新画像 — 学习节奏（用实际耗时）
        # profiles 有 UNIQUE(user_id,dimension,field) 约束，必须 upsert，
        # 否则同一个用户第二次通过练习就会撞唯一键导致整个接口 500。
        profile_utils.upsert(
            user_id, session_id, "learning_pace", "avg_session_minutes",
            str(time_spent), 0.7, req.topic,
        )
        # 已知概念是列表型字段，单行存 JSON 数组并追加去重
        profile_utils.append_list(
            user_id, session_id, "knowledge_base", "known_concepts",
            req.topic, 0.8, f"练习通过{req.topic}({score_pct}%)",
        )

        path_data, path_id = _load_path_data(session_id)
        phases = path_data.get("phases", [])

        # ── 完成规则：练习通过 + 已开始学习 → 才算完成 ──
        started = any(
            t.get("title") == req.topic or t.get("topic_id") == req.topic
            for phase in phases for t in phase.get("topics", [])
            if t.get("status") in ("in_progress", "completed")
        )
        # 没有子 topic 的 phase（phase 本身是主题）
        started = started or any(
            p.get("title") == req.topic and p.get("status") in ("in_progress", "completed")
            for p in phases
        )

        if started:
            completed_now = _apply_topic_status(phases, req.topic, "completed")
            if completed_now:
                _unlock_next_topic(phases, req.topic)
            _save_path_data(session_id, path_id, path_data)
            path_updated = True
        else:
            # 还没开始学习 → 只记为"已开始"，等开始学习时自动补完成
            _apply_topic_status(phases, req.topic, "in_progress")
            _save_path_data(session_id, path_id, path_data)

    if passed and path_updated:
        message = f"🎉 恭喜通过！正确率 {score_pct}%，该主题已完成，已解锁下一阶段。"
    elif passed:
        message = (
            f"🎉 练习通过了（正确率 {score_pct}%）！不过「{req.topic}」还没开始学习——"
            f"去点「💬 开始学习」学一遍，两边都完成就能解锁下一阶段。"
        )
    else:
        message = f"📉 正确率 {score_pct}%，还需达到 60% 才能通过。再接再厉！"

    # ── 错题入库（无论通过与否，做错的题都进错题本）──
    # 同一题干重复做错只累加 wrong_count，不重复插行，避免错题本越滚越长。
    for m in (req.mistakes or [])[:20]:   # 上限 20 道，防御异常数据
        stem = str(m.get("stem", "")).strip()
        if not stem:
            continue
        existing = db.fetch_one(
            "SELECT id, wrong_count FROM wrong_questions WHERE session_id = ? AND stem = ?",
            (session_id, stem),
        )
        if existing:
            db.execute(
                """UPDATE wrong_questions
                   SET wrong_count = wrong_count + 1, user_answer = ?, resolved = 0, topic = ?
                   WHERE id = ?""",
                (str(m.get("user_answer", ""))[:255], req.topic, existing["id"]),
            )
        else:
            db.execute(
                """INSERT INTO wrong_questions
                   (session_id, user_id, topic, stem, options_json, answer, user_answer, explanation)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, user_id, req.topic, stem,
                    json.dumps(m.get("options", []), ensure_ascii=False),
                    str(m.get("answer", ""))[:255],
                    str(m.get("user_answer", ""))[:255],
                    str(m.get("explanation", "")),
                ),
            )
        mistakes_saved += 1

    # 做错的主题写入画像 error_patterns（易错主题），供内容生成/出题时针对性加强。
    # append_list 内部会去重追加，重复错同一主题不会撑爆列表。
    if req.mistakes:
        try:
            profile_utils.append_list(
                user_id, session_id, "error_patterns", "error_prone_topics",
                req.topic, 0.85, f"练习做错{req.topic}({score_pct}%)",
            )
        except Exception as e:
            print(f"[practice] 写入易错主题失败（不影响主流程）: {e}")

    if mistakes_saved:
        message += f" 已把 {mistakes_saved} 道错题收进错题本 🔁。"

    return {
        "passed": passed,
        "score_pct": score_pct,
        "path_updated": path_updated,
        "mistakes_saved": mistakes_saved,
        "message": message,
    }


@router.get("/learning-path/{session_id}/wrong-questions")
def get_wrong_questions(session_id: str):
    """错题本：返回未掌握（resolved=0）的错题，按做错次数降序"""
    session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if not session_row:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = db.fetch_all(
        """SELECT id, topic, stem, options_json, answer, user_answer, explanation,
                  wrong_count, created_at
           FROM wrong_questions
           WHERE session_id = ? AND resolved = 0
           ORDER BY wrong_count DESC, created_at DESC
           LIMIT 50""",
        (session_id,),
    )
    items = []
    for r in rows:
        try:
            options = json.loads(r.get("options_json") or "[]")
        except Exception:
            options = []
        items.append({
            "id": r["id"],
            "topic": r.get("topic", ""),
            "stem": r.get("stem", ""),
            "options": options,
            "answer": r.get("answer", ""),
            "user_answer": r.get("user_answer", ""),
            "explanation": r.get("explanation", ""),
            "wrong_count": r.get("wrong_count", 1),
            "created_at": str(r.get("created_at", "")),
        })
    return {"wrong_questions": items, "total": len(items)}


@router.post("/learning-path/{session_id}/wrong-questions/{question_id}/resolve")
def resolve_wrong_question(session_id: str, question_id: int):
    """把错题标记为已掌握（做对同题或用户点「掌握了」）"""
    session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if not session_row:
        raise HTTPException(status_code=404, detail="会话不存在")
    row = db.fetch_one(
        "SELECT id FROM wrong_questions WHERE id = ? AND session_id = ?",
        (question_id, session_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="错题不存在")
    db.execute(
        "UPDATE wrong_questions SET resolved = 1 WHERE id = ?",
        (question_id,),
    )
    return {"ok": True, "message": "已标记掌握，从复习清单移除"}
