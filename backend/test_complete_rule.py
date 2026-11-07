# -*- coding: utf-8 -*-
"""端到端验证主题完成新规则：开始学习 + 练练手通过 才算完成（顺序不限）"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from app.db.sqlite_client import db
from app.api.learning_path import (
    start_topic, complete_topic, submit_practice, _load_path_data,
)
from app.models.learning_path import (
    StartTopicRequest, CompleteTopicRequest, SubmitPracticeRequest,
)
import uuid

# ── 建测试用户 + 会话（不碰真实数据） ──
uid = f"user_test_rule_{uuid.uuid4().hex[:6]}"
sid = f"sess_test_rule_{uuid.uuid4().hex[:6]}"
db.execute("INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'x')", (uid, f"test_rule_{uuid.uuid4().hex[:6]}"))
db.execute("INSERT INTO sessions (id, user_id, course) VALUES (?, ?, 'Python程序设计')", (sid, uid))
print(f"测试会话: {sid}")

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []


def topic_status(topic_title):
    path_data, _ = _load_path_data(sid)
    for phase in path_data.get("phases", []):
        for t in phase.get("topics", []):
            if t.get("title") == topic_title:
                return t.get("status")
    return None


def next_status(topic_title):
    path_data, _ = _load_path_data(sid)
    for phase in path_data.get("phases", []):
        topics = phase.get("topics", [])
        for i, t in enumerate(topics):
            if t.get("title") == topic_title and i + 1 < len(topics):
                return topics[i + 1].get("title")  # 返回下一个主题的标题
    return None


def first_available_topic():
    path_data, _ = _load_path_data(sid)
    for phase in path_data.get("phases", []):
        for t in phase.get("topics", []):
            if t.get("status") == "available":
                return t.get("title")
    return None


try:
    t1 = first_available_topic()
    t2 = None
    # 找 t1 的下一个主题
    path_data, _ = _load_path_data(sid)
    for phase in path_data.get("phases", []):
        topics = phase.get("topics", [])
        for i, t in enumerate(topics):
            if t.get("title") == t1 and i + 1 < len(topics):
                t2 = topics[i + 1].get("title")
    print(f"测试主题: t1={t1}, t2={t2}")

    # ── 情形1：没开始学习，直接练练手通过 → 只算"已开始"，不算完成 ──
    r = submit_practice(sid, SubmitPracticeRequest(
        topic=t1, correct=5, total=5, resource_id="", time_spent_minutes=3))
    ok1 = r["passed"] and not r["path_updated"] and topic_status(t1) == "in_progress"
    results.append((f"情形1 练习通过但未开始学习 → in_progress 不完成", ok1, f"status={topic_status(t1)}, path_updated={r['path_updated']}"))

    # ── 情形2：之后点「开始学习」→ 练习已通过，自动补成完成 + 解锁下一个 ──
    r2 = start_topic(sid, StartTopicRequest(topic=t1))
    nxt = next_status(t1)  # 下一个主题的标题
    ok2 = r2["completed"] and topic_status(t1) == "completed" and (nxt is None or topic_status(nxt) != "locked")
    results.append((f"情形2 后补开始学习 → 自动完成并解锁", ok2, f"status={topic_status(t1)}, next({nxt})={topic_status(nxt) if nxt else '无'}"))

    # ── 情形3：先开始学习 → in_progress；再练练手通过 → 完成 ──
    r3 = start_topic(sid, StartTopicRequest(topic=t2))
    ok3a = (not r3["completed"]) and topic_status(t2) == "in_progress"
    results.append((f"情形3a 先开始学习 → in_progress", ok3a, f"status={topic_status(t2)}"))

    r4 = submit_practice(sid, SubmitPracticeRequest(
        topic=t2, correct=4, total=5, resource_id="", time_spent_minutes=2))
    ok3b = r4["passed"] and r4["path_updated"] and topic_status(t2) == "completed"
    results.append((f"情形3b 再练习通过 → 完成", ok3b, f"status={topic_status(t2)}, path_updated={r4['path_updated']}"))

    # ── 情形4：聊天里说"学完了"（complete_topic）→ 只是记为开始，不算完成 ──
    t3 = next_status(t2)
    if t3:
        # 先解锁 t3 方便测试（把 t2 完成 + unlock 已做，t3 应该 available）
        r5 = complete_topic(sid, CompleteTopicRequest(
            topic=t3, resource_id="", time_spent_minutes=5, self_evaluation="聊天说学完了"))
        ok4 = (not r5["completed"]) and topic_status(t3) == "in_progress"
        results.append((f"情形4 聊天说学完了 → 只记开始不完成", ok4, f"status={topic_status(t3)}, completed={r5['completed']}"))
    else:
        results.append(("情形4 聊天说学完了 → 只记开始不完成", False, "没有可用主题"))

    # ── 情形5：练习不通过 → 永远不算完成 ──
    r6 = submit_practice(sid, SubmitPracticeRequest(
        topic=t2, correct=1, total=5, resource_id="", time_spent_minutes=1))
    ok5 = (not r6["passed"]) and topic_status(t2) == "completed"  # 已完成的保持完成，不回退
    results.append((f"情形5 已完成主题再练失败 → 状态保持完成", ok5, f"status={topic_status(t2)}"))

    print()
    all_ok = True
    for name, ok, detail in results:
        print(f"{PASS if ok else FAIL}  {name}   ({detail})")
        all_ok = all_ok and ok
    print()
    print("全部通过 🎉" if all_ok else "存在失败项！")
finally:
    # 清理测试数据
    db.execute("DELETE FROM learning_records WHERE session_id = ?", (sid,))
    db.execute("DELETE FROM learning_paths WHERE session_id = ?", (sid,))
    db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    db.execute("DELETE FROM profiles WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    print("(测试数据已清理)")
