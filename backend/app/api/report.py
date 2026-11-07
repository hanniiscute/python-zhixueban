"""AI 学习报告 API — 汇总学习数据，交由大模型生成个性化 Markdown 报告"""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.db.sqlite_client import db
from app.core.llm_client import spark_llm
from app.api.evaluation import get_stats
from app.core import profile_utils

router = APIRouter(prefix="/api", tags=["学习报告"])


def _collect_report_data(session_id: str) -> dict:
    """汇总报告所需的一切数据（复用 evaluation 的统计口径）"""
    stats = get_stats(session_id)   # 内部已做会话存在性校验

    # 错题分布：按主题聚合未掌握的错题
    wrong_rows = db.fetch_all(
        """SELECT topic, COUNT(*) AS cnt FROM wrong_questions
           WHERE session_id = ? AND resolved = 0
           GROUP BY topic ORDER BY cnt DESC LIMIT 8""",
        (session_id,),
    )
    weak_topics = [{"topic": r.get("topic") or "未分类", "count": r["cnt"]} for r in wrong_rows]

    # 最近练习记录（主题 + 得分），最多 10 条
    recent_rows = db.fetch_all(
        """SELECT topic, self_evaluation, created_at FROM learning_records
           WHERE session_id = ? AND self_evaluation LIKE ?
           ORDER BY created_at DESC LIMIT 10""",
        (session_id, "%练习得分%"),
    )
    recent_practice = []
    for r in recent_rows:
        recent_practice.append({
            "topic": r.get("topic", ""),
            "result": r.get("self_evaluation", ""),
            "date": str(r.get("created_at", "")),
        })

    # 学习画像摘要（水平、兴趣、易错模式等）
    profile = profile_utils.get_profile_summary_by_session(session_id)

    return {"stats": stats, "weak_topics": weak_topics,
            "recent_practice": recent_practice, "profile": profile}


def _build_prompt(data: dict) -> list[dict]:
    stats = data["stats"]
    data_json = json.dumps(data, ensure_ascii=False, default=str)
    system = (
        "你是一位耐心的 Python 学习助教，负责给学生写学习报告。"
        "报告用简体中文、Markdown 格式，语气亲切像学长，多用具体数字说话，不要空洞鸡汤。"
        "结构固定为：\n"
        "## 📊 整体表现\n（两三句话总结，给出综合评价）\n"
        "## 💪 做得好的地方\n（2-3 条，结合数据）\n"
        "## 📌 需要加强的地方\n（结合薄弱主题和错题分布，指出具体要补什么）\n"
        "## 🎯 下一步建议\n（3 条以内，每条都可执行，如'重做 XX 主题的错题'）\n"
        "不要编造数据里没有的信息；数据不足时如实说'记录还少，继续学习后报告会更有参考价值'。"
    )
    user = (
        f"以下是学生的统计数据 JSON，请据此生成学习报告：\n{data_json}\n\n"
        f"关键数字提醒：累计学习 {stats.get('total_learning_minutes', 0)} 分钟，"
        f"完成主题 {stats.get('topics_completed', 0)} 个，"
        f"练习 {stats.get('quiz_attempts', 0)} 次平均正确率 {stats.get('quiz_accuracy', 0)}%，"
        f"连续学习 {stats.get('daily_streak', 0)} 天。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


@router.post("/report/{session_id}/generate")
def generate_report(session_id: str):
    """生成（并缓存）AI 学习报告"""
    data = _collect_report_data(session_id)
    stats = data["stats"]

    # 完全没有学习记录时不必浪费一次大模型调用
    if stats.get("total_learning_minutes", 0) == 0 and stats.get("quiz_attempts", 0) == 0 \
            and stats.get("questions_asked", 0) == 0:
        raise HTTPException(status_code=400, detail="还没有学习记录，先去聊聊天或练练手吧！")

    try:
        report_md = spark_llm.chat_sync(_build_prompt(data), max_tokens=2048)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"报告生成失败: {e}")
    if report_md.startswith("[星火API错误]"):
        raise HTTPException(status_code=502, detail=report_md)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"report": report_md, "stats": stats, "generated_at": generated_at}

    # 缓存到 evaluations 表（eval_type='report'，同会话只留最新一份）
    existing = db.fetch_one(
        "SELECT id FROM evaluations WHERE session_id = ? AND eval_type = 'report'",
        (session_id,),
    )
    data_json = json.dumps(payload, ensure_ascii=False)
    if existing:
        db.execute(
            "UPDATE evaluations SET data_json = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?",
            (data_json, existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO evaluations (id, session_id, eval_type, data_json) VALUES (?, ?, 'report', ?)",
            (f"report_{session_id[:32]}", session_id, data_json),
        )

    return payload


@router.get("/report/{session_id}")
def get_cached_report(session_id: str):
    """读取上次生成的报告（没有则返回 null，前端提示先生成）"""
    row = db.fetch_one(
        "SELECT data_json, created_at FROM evaluations WHERE session_id = ? AND eval_type = 'report'",
        (session_id,),
    )
    if not row:
        return {"report": None}
    try:
        payload = json.loads(row["data_json"])
    except Exception:
        return {"report": None}
    return payload
