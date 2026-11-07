"""画像（profiles）写入统一入口。

背景：profiles 表有 UNIQUE(user_id, dimension, field) 约束 —— 同一个用户的同一个
字段只允许存在一行。历史上多处直接写裸 INSERT，第二次调用会撞唯一键导致接口 500，
表现有三：
  · 第二次提交练习题就崩（learning_path.submit_practice）
  · 问卷重做一次就崩（profile.save_questionnaire）
  · 给第二份学习资源反馈难度就崩（resources.submit_feedback）

所有写 profiles 的地方都必须走这里的 upsert / append_list，不要再写裸 INSERT。

列表型字段（如 knowledge_base.known_concepts）因为每个字段只保留一行，
必须在 DB 里单行存 JSON 数组，读取时 json.loads 还原 —— 见 append_list / read_list。
"""

import json

from app.db.sqlite_client import db


def upsert(user_id, session_id, dimension, field, value, confidence=0.7, evidence=""):
    """写入或覆盖一条画像。同一 (user_id, dimension, field) 已存在则更新为新值。"""
    db.execute(
        """INSERT INTO profiles (user_id, session_id, dimension, field, value, confidence, evidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON DUPLICATE KEY UPDATE
               session_id = VALUES(session_id),
               value = VALUES(value),
               confidence = VALUES(confidence),
               evidence = VALUES(evidence),
               created_at = CURRENT_TIMESTAMP""",
        (user_id, session_id, dimension, field, str(value), confidence, evidence or ""),
    )


def read_value(user_id, dimension, field):
    """读取某个画像字段的原始字符串值，不存在返回 None。"""
    row = db.fetch_one(
        "SELECT value FROM profiles WHERE user_id = ? AND dimension = ? AND field = ?",
        (user_id, dimension, field),
    )
    return row["value"] if row else None


def read_list(user_id, dimension, field):
    """读取列表型画像字段，自动把 JSON 数组/历史脏字符串还原成 list[str]。"""
    raw = read_value(user_id, dimension, field)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [str(parsed)]
    except Exception:
        return [str(raw)]


def append_list(user_id, session_id, dimension, field, items,
                confidence=0.8, evidence=""):
    """向列表型画像字段追加值（自动去重）。返回是否真的有新内容写入。

    列表字段在库里只有一行，所以必须先读旧的 → 追加 → 整行写回，不能裸 INSERT。
    """
    if isinstance(items, str):
        items = [items]
    current = read_list(user_id, dimension, field)
    added = False
    for it in items:
        if it and it not in current:
            current.append(it)
            added = True
    if not added:
        return False
    upsert(user_id, session_id, dimension, field,
           json.dumps(current, ensure_ascii=False), confidence, evidence)
    return True


# ================================================================
# 读取：按 session 拿完整画像
# ================================================================

def get_profile_summary_by_session(session_id: str) -> dict:
    """按 session_id 取出该用户的完整画像（{dimension: {field: value}}）。

    画像按 user_id 维度存储（同一用户跨会话共享一份），所以必须先由 session
    反查 user_id，不能直接 `WHERE session_id = ?` —— 那样在别的会话写入的画像
    就读不到，导致难度/个性化失效。
    """
    row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
    if row and row.get("user_id"):
        rows = db.fetch_all(
            "SELECT dimension, field, value FROM profiles WHERE user_id = ?",
            (row["user_id"],),
        )
    else:
        # 兜底：session 查不到时按 session_id 读（兼容历史/异常数据）
        rows = db.fetch_all(
            "SELECT dimension, field, value FROM profiles WHERE session_id = ?",
            (session_id,),
        )
    p = {}
    for r in rows:
        p.setdefault(r["dimension"], {})[r["field"]] = r["value"]
    return p
