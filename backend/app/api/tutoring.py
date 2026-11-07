"""智能辅导 API — 答疑历史 + 错题针对性讲解"""

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.db.sqlite_client import db

router = APIRouter(prefix="/api", tags=["智能辅导"])

# 答疑式提问的特征词（与 orchestrator 的 ask 意图关键词保持一致，另加问号兜底）
_ASK_HINTS = ("为什么", "报错", "错误", "不会", "怎么办", "怎么改", "怎么解决",
              "搞不懂", "看不懂", "困惑", "啥意思", "什么意思", "如何解决")
_QUESTION_MARKS = ("？", "?")


def _looks_like_question(content: str) -> bool:
    """判断一条用户消息是否是答疑式提问"""
    if any(h in content for h in _ASK_HINTS):
        return True
    return any(m in content for m in _QUESTION_MARKS)


@router.get("/tutoring/{session_id}")
def get_tutoring_history(session_id: str, page: int = 1, size: int = 20):
    """获取答疑历史：从对话记录中提取「提问 → 解答」对，按时间倒序分页返回"""
    page = max(1, page)
    size = max(1, min(size, 100))

    rows = db.fetch_all(
        """SELECT id, role, content, created_at
           FROM chat_messages WHERE session_id = %s
           ORDER BY id ASC""",
        (session_id,),
    ) or []

    # 配对：用户提问 + 其后第一条 assistant 回复
    pairs = []
    i = 0
    while i < len(rows):
        r = rows[i]
        if r["role"] == "user" and _looks_like_question(r["content"] or ""):
            answer = None
            j = i + 1
            while j < len(rows):
                if rows[j]["role"] == "assistant":
                    answer = rows[j]["content"]
                    break
                if rows[j]["role"] == "user":  # 连续提问，取下一条配对
                    break
                j += 1
            created = r["created_at"]
            pairs.append({
                "id": f"qa_{r['id']}",
                "question": (r["content"] or "").strip(),
                "answer": (answer or "").strip() if answer else None,
                "answered": bool(answer),
                "asked_at": created.strftime("%Y-%m-%d %H:%M:%S") if hasattr(created, "strftime") else str(created),
            })
            i = (j + 1) if answer else (i + 1)
        else:
            i += 1

    # 时间倒序分页（最近的提问在前）
    pairs.reverse()
    total = len(pairs)
    start = (page - 1) * size
    return {
        "total": total,
        "page": page,
        "size": size,
        "questions": pairs[start:start + size],
    }


# ============ 错题针对性讲解 ============

class ExplainMistakesRequest(BaseModel):
    session_id: str
    topic: str = ""
    mistakes: list = Field(default_factory=list)  # [{stem, options, answer(s), user_answer, explanation}]


@router.post("/tutoring/explain-mistakes")
def explain_mistakes(req: ExplainMistakesRequest, request: Request):
    """针对本次练习的错题生成一份集中讲解（同步接口，前端提交答案后调用）

    讲解内容：逐题说明错因（学生选错的那个选项错在哪）、补齐知识点、
    最后给一条通用的避坑建议。个性化：注入学生画像调整讲解深度。
    """
    from app.core.llm_client import spark_llm
    from app.core import profile_utils

    # 会话归属校验（session_id 在 body 里，路径上没有 sess_ 段，中间件覆盖不到）
    user_id = getattr(request.state, "user_id", None)
    sess = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (req.session_id,))
    if user_id and sess and sess["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    if not req.mistakes:
        return {"explanation": ""}

    profile = profile_utils.get_profile_summary_by_session(req.session_id)
    kb = profile.get("knowledge_base", {})
    level = kb.get("level", "了解一点") if isinstance(kb, dict) else "了解一点"
    error_patterns = json.dumps(profile.get("error_patterns", {}), ensure_ascii=False) if profile else "{}"

    mistakes_text = json.dumps(req.mistakes, ensure_ascii=False)

    system_prompt = (
        "你是一位耐心的Python助教。学生刚做完一组练习题，下面是他的错题记录。"
        f"学生水平：{level}；历史易错点：{error_patterns}\n"
        "请用 Markdown 逐题讲解，格式：\n"
        "## 错题讲解\n\n"
        "### 第N题：<题干摘要>\n"
        "- ✅ 正确答案：X，用一两句大白话说清为什么对\n"
        "- ❌ 你选了 Y：指出这个选择的思路错在哪（对他的真实错误成因归因，不要套话）\n"
        "- 💡 一句话记住它\n\n"
        "最后一节用「📌 这次要记住」总结 1-2 条通用避坑建议。"
        "语言口语化、面向大学生，总长度控制在 300 字以内，不要复述完整题干。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"主题：{req.topic or '综合练习'}\n错题记录（JSON）：{mistakes_text}\n"
            "请生成错题讲解。只输出 Markdown，不要输出其它内容。"
        )},
    ]

    try:
        raw = spark_llm.chat_sync(messages, max_tokens=1536)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI服务调用失败: {str(e)[:100]}")

    return {"explanation": (raw or "").strip()}
