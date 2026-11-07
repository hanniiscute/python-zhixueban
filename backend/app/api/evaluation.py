"""学习效果评估 API"""

import json
from fastapi import APIRouter, HTTPException
from app.db.sqlite_client import db

router = APIRouter(prefix="/api", tags=["学习评估"])


def _get_completed_topics(session_id: str) -> int:
    """从学习路径 JSON 中统计已完成 topic 数"""
    row = db.fetch_one(
        "SELECT path_json FROM learning_paths WHERE session_id = %s",
        (session_id,)
    )
    if not row or not row.get("path_json"):
        return 0
    try:
        data = json.loads(row["path_json"])
    except json.JSONDecodeError:
        return 0

    count = 0
    for phase in data.get("phases", []):
        for topic in phase.get("topics", []):
            if topic.get("status") == "completed":
                count += 1
    return count


def _get_total_topics(session_id: str) -> int:
    """统计总 topic 数"""
    row = db.fetch_one(
        "SELECT path_json FROM learning_paths WHERE session_id = %s",
        (session_id,)
    )
    if not row or not row.get("path_json"):
        return 0
    try:
        data = json.loads(row["path_json"])
    except json.JSONDecodeError:
        return 0

    count = 0
    for phase in data.get("phases", []):
        count += len(phase.get("topics", []))
    return count


@router.get("/evaluation/{session_id}")
def get_evaluation(session_id: str, scope: str = "overall"):
    """获取评估报告"""
    # 验证 session 存在
    session = db.fetch_one("SELECT id FROM sessions WHERE id = %s", (session_id,))
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    total = _get_total_topics(session_id)
    completed = _get_completed_topics(session_id)

    # 知识掌握度：基于完成比例
    knowledge_score = round(completed / total * 100, 1) if total > 0 else 0

    # 学习投入度：基于学习时长
    time_row = db.fetch_one(
        "SELECT COALESCE(SUM(time_spent_minutes), 0) AS total_min FROM learning_records WHERE session_id = %s",
        (session_id,)
    )
    total_min = int(time_row["total_min"]) if time_row else 0
    engagement_score = min(100, round(total_min / 600 * 100, 1)) if total_min > 0 else 0  # 600分钟=10小时视为100%

    # 练习正确率
    quiz_rows = db.fetch_all(
        "SELECT self_evaluation FROM learning_records WHERE session_id = %s AND self_evaluation LIKE %s",
        (session_id, "%练习得分%")
    )
    quiz_accuracy = 0.0
    if quiz_rows:
        total_correct = 0
        total_questions = 0
        for r in quiz_rows:
            eval_str = r.get("self_evaluation", "")
            # 格式: "练习得分: 4/5 (80.0%) - 通过"
            try:
                # 格式: "练习得分: 4/5 (80.0%) - 通过"
                score_part = eval_str.replace("练习得分:", "").strip().split(" ")[0]
                correct, total_q = score_part.split("/")
                total_correct += int(correct)
                total_questions += int(total_q)
            except (ValueError, AttributeError):
                pass
        quiz_accuracy = round(total_correct / total_questions * 100, 1) if total_questions > 0 else 0

    # 学习效率：完成的 topic 数 / 学习小时数
    hours = total_min / 60 if total_min > 0 else 0
    efficiency = min(100, round(completed / hours * 20, 1)) if hours > 0 and completed > 0 else 0

    # 生成摘要
    if completed == 0 and total_min == 0:
        summary = "你还没有开始学习，去学习路径开始你的第一步吧！"
    elif knowledge_score >= 80:
        summary = f"你已经完成了 {completed}/{total} 个主题，掌握度 {knowledge_score}%，继续保持！"
    elif knowledge_score >= 40:
        summary = f"学习进展中，已完成 {completed}/{total} 个主题。多练练手可以加速进步。"
    else:
        summary = f"刚开始学习之旅，已完成 {completed}/{total} 个主题。坚持就是胜利！"

    # 生成调整建议
    adjustments = []
    if quiz_accuracy < 60 and quiz_rows:
        adjustments.append({
            "target": "练习正确率",
            "action": "建议多回顾知识点再练练手",
            "reason": f"当前正确率 {quiz_accuracy}%，低于通过线 60%"
        })
    if engagement_score < 30:
        adjustments.append({
            "target": "学习投入",
            "action": "建议每天至少安排30分钟学习",
            "reason": f"累计学习仅 {total_min} 分钟，投入度偏低"
        })
    if efficiency > 0 and efficiency < 40:
        adjustments.append({
            "target": "学习效率",
            "action": "建议在练习前先浏览相关知识点",
            "reason": "主题推进偏慢，可能基础知识需要巩固"
        })

    return {
        "report_id": f"eval_{session_id}",
        "scope": scope,
        "generated_at": "",
        "summary": summary,
        "dimensions": [
            {
                "name": "知识掌握度",
                "score": knowledge_score,
                "trend": "up" if completed > 0 else "stable",
                "detail": f"已完成 {completed}/{total} 个学习主题"
            },
            {
                "name": "学习投入度",
                "score": engagement_score,
                "trend": "up" if total_min > 60 else "stable",
                "detail": f"累计学习 {total_min} 分钟"
            },
            {
                "name": "练习正确率",
                "score": quiz_accuracy,
                "trend": "up" if quiz_accuracy >= 60 else "stable",
                "detail": f"{len(quiz_rows)} 次练习记录" if quiz_rows else "暂无练习记录"
            },
            {
                "name": "学习效率",
                "score": efficiency,
                "trend": "stable",
                "detail": f"约 {round(hours, 1)} 小时完成 {completed} 个主题" if hours > 0 else "尚未开始学习"
            },
        ],
        "adjustments": adjustments,
    }


@router.get("/evaluation/{session_id}/stats")
def get_stats(session_id: str):
    """获取学习统计"""
    session = db.fetch_one("SELECT id FROM sessions WHERE id = %s", (session_id,))
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 学习时长
    time_row = db.fetch_one(
        "SELECT COALESCE(SUM(time_spent_minutes), 0) AS total_min FROM learning_records WHERE session_id = %s",
        (session_id,)
    )
    total_learning_minutes = int(time_row["total_min"]) if time_row else 0

    # 完成 topic 数
    topics_completed = _get_completed_topics(session_id)

    # 资源数
    resources_row = db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM resources WHERE session_id = %s",
        (session_id,)
    )
    resources_consumed = resources_row["cnt"] if resources_row else 0

    # 练习统计
    quiz_rows = db.fetch_all(
        "SELECT self_evaluation FROM learning_records WHERE session_id = %s AND self_evaluation LIKE %s",
        (session_id, "%练习得分%")
    )
    quiz_attempts = len(quiz_rows)
    quiz_accuracy = 0.0
    if quiz_rows:
        total_correct = 0
        total_questions = 0
        for r in quiz_rows:
            eval_str = r.get("self_evaluation", "")
            try:
                # 格式: "练习得分: 4/5 (80.0%) - 通过"
                score_part = eval_str.replace("练习得分:", "").strip().split(" ")[0]
                correct, total_q = score_part.split("/")
                total_correct += int(correct)
                total_questions += int(total_q)
            except (ValueError, AttributeError):
                pass
        quiz_accuracy = round(total_correct / total_questions * 100, 1) if total_questions > 0 else 0

    # 提问数
    msg_row = db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM chat_messages WHERE session_id = %s AND role = 'user'",
        (session_id,)
    )
    questions_asked = msg_row["cnt"] if msg_row else 0

    # 连续学习天数
    streak_row = db.fetch_all(
        "SELECT DISTINCT DATE(created_at) AS learn_date FROM learning_records WHERE session_id = %s ORDER BY learn_date DESC",
        (session_id,)
    )
    daily_streak = 0
    if streak_row:
        from datetime import date, timedelta
        today = date.today()
        for i, r in enumerate(streak_row):
            expected = today - timedelta(days=i)
            actual = r["learn_date"]
            if isinstance(actual, str):
                actual = date.fromisoformat(actual)
            if actual == expected:
                daily_streak += 1
            else:
                break

    # 时间线（按天聚合学习记录）
    timeline_rows = db.fetch_all(
        """SELECT DATE(created_at) AS d, COUNT(*) AS actions,
                  COALESCE(SUM(time_spent_minutes), 0) AS minutes
           FROM learning_records WHERE session_id = %s
           GROUP BY DATE(created_at) ORDER BY d ASC""",
        (session_id,)
    )
    timeline = []
    if timeline_rows:
        for r in timeline_rows:
            timeline.append({
                "date": r["d"].strftime("%Y-%m-%d") if hasattr(r["d"], "strftime") else str(r["d"]),
                "actions": r["actions"],
                "minutes": int(r["minutes"]),
            })

    return {
        "total_learning_minutes": total_learning_minutes,
        "topics_completed": topics_completed,
        "resources_consumed": resources_consumed,
        "quiz_attempts": quiz_attempts,
        "quiz_accuracy": quiz_accuracy,
        "questions_asked": questions_asked,
        "daily_streak": daily_streak,
        "timeline": timeline,
    }
