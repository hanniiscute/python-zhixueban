"""拓展阅读意图接线验证

覆盖三层：
 1) detect_intent 的意图分类（强制走关键词回退路径 = embedding 不可用时的最坏情况）
 2) INTENT_AGENT 映射
 3) handle_message 的冷启动豁免（reading 不能被画像问卷劫持）
"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.orchestrator import Orchestrator

fails = []


def new_orch():
    o = Orchestrator()
    # embedding 需要联网，这里隔离掉，保证测试确定性
    o.intent_classifier.classify = lambda msg, min_similarity=0.25: ("", 0.0)
    return o


o = new_orch()

CASES = [
    # 新增：拓展阅读
    ("推荐一些Python进阶的书", "reading"),
    ("有什么好书推荐", "reading"),
    ("有没有进阶的学习资料", "reading"),
    ("推荐几个练手的开源项目", "reading"),
    ("推荐几本讲爬虫的书", "reading"),        # 不能被 code 的"爬虫"抢走
    ("推荐学习资料", "reading"),             # 不能被 learn 的"学习"抢走
    ("拓展阅读", "reading"),
    ("参考资料", "reading"),
    # 回归：这些不能被 reading 抢走
    ("我想学习：for循环", "learn"),
    ("教我一下装饰器", "learn"),
    ("给我出几道列表的练习题", "practice"),
    ("帮我推荐一道练习题", "practice"),
    ("生成for循环的思维导图", "mindmap"),
    ("推荐一个思维导图模板", "mindmap"),
    ("帮我写一个爬虫", "code"),
    ("帮我规划学习路径", "path"),
    ("学得怎么样", "evaluate"),
    ("为什么我的代码报错了", "ask"),
    ("我这个项目有没有bug", "ask"),          # 名词在前、动词在后 → 不能判成要资源
    # want=None 表示只要求"不能被 reading 抢走"，不锁定具体意图
    # （"推荐学习顺序" 命中 learn 的弱关键词"学习"，是本次改动之前就有的行为）
    ("推荐学习顺序", None),
]

print("=== 1) 意图分类（关键词回退路径）===")
for msg, want in CASES:
    got = o.detect_intent(msg)
    ok = (got != "reading") if want is None else (got == want)
    if not ok:
        fails.append((msg, want or "≠reading", got))
    expect_txt = "≠reading" if want is None else f"期望 {want}"
    print(f"  {'OK  ' if ok else 'FAIL'} {msg!r:30s} → {got:10s} ({expect_txt})")

print("\n=== 2) 映射表 ===")
mapped = o.intent_classifier.INTENT_AGENT.get("reading")
ok = mapped == "reading_gen"
if not ok:
    fails.append(("INTENT_AGENT['reading']", "reading_gen", mapped))
print(f"  {'OK  ' if ok else 'FAIL'} INTENT_AGENT['reading'] = {mapped!r}")

# 映射表里每个意图都必须有对应智能体注册（chat.py 的 _register_agents）
REGISTERED = {"profiler", "content_gen", "mindmap_gen", "reading_gen",
              "quiz_gen", "code_agent", "path_planner", "tutor", "evaluator"}
missing = {v for v in o.intent_classifier.INTENT_AGENT.values() if v not in REGISTERED}
ok = not missing
if not ok:
    fails.append(("未注册的智能体", "无", missing))
print(f"  {'OK  ' if ok else 'FAIL'} 所有意图都有已注册的智能体承接 "
      f"（缺失: {missing or '无'}）")


async def noop(*a, **k):
    return None


class FakeAgent:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    async def process(self, conn_id, session_id, message, context=None):
        self.calls += 1


async def cold_start(msg) -> dict:
    """画像维度为 0 时，消息实际被派发给哪个智能体"""
    o2 = new_orch()
    o2._count_profile_dimensions = lambda sid: 0
    o2._count_messages = lambda sid: 1
    o2.save_message = lambda *a, **k: None
    o2.load_history = lambda *a, **k: []
    agents = {n: FakeAgent(n) for n in ("reading_gen", "profiler", "evaluator", "mindmap_gen")}
    for n, a in agents.items():
        o2.register_agent(n, a)
    with patch("app.core.orchestrator.sse_manager.send_event", new=noop):
        await o2.handle_message("conn1", "sess_test", msg)
    return {n: a.calls for n, a in agents.items() if a.calls}


print("\n=== 3) 冷启动豁免（画像维度 < 3）===")
CHECKS = [
    ("推荐一些书", "reading_gen"),   # 明确要资源 → 不能被画像问卷劫持
    ("学得怎么样", "evaluator"),      # 依赖真实数据 → 必须豁免
    ("生成思维导图", "profiler"),     # 无豁免 → 按原设计先补画像
]
for msg, want in CHECKS:
    got = asyncio.run(cold_start(msg))
    dispatched = next(iter(got), None)
    ok = dispatched == want
    if not ok:
        fails.append((msg + " [冷启动]", want, dispatched))
    print(f"  {'OK  ' if ok else 'FAIL'} {msg!r:16s} → 派发给 {dispatched:12s} (期望 {want})")

print("\n=== 4) ReadingAgent 端到端（模板加载 / 占位符 / 画像注入 / 话题清洗）===")

import app.agents.content_gen as cg
from app.agents.content_gen import reading_agent

# 4.1 prompts.yaml 里必须有 reading_gen 章节，否则退回硬编码兜底提示词
tpl = reading_agent._get_system_prompt()
ok = bool(tpl.strip())
if not ok:
    fails.append(("prompts.yaml reading_gen", "非空", "空"))
print(f"  {'OK  ' if ok else 'FAIL'} prompts.yaml 加载到 reading_gen 模板（{len(tpl)} 字符）")


async def reading_run(msg):
    cap = {}

    async def fake_stream(conn_id, sse_manager, messages, event_type="content",
                          max_tokens=4096, session_id=None):
        cap["messages"] = messages
        cap["session_id"] = session_id
        return "【测试输出】"

    reading_agent._stream_llm = fake_stream
    reading_agent._get_profile_summary = lambda sid: {
        "knowledge_base": {"level": "比较熟练"},
        "interest_tendency": {"directions": '["数据分析/AI"]'},
        "learning_style": {"type": "visual"},
        "error_patterns": {"error_prone_topics": '["闭包作用域"]'},
    }
    events = []

    async def rec_event(conn_id, name, data):
        events.append((name, data))

    with patch.object(cg.retriever, "retrieve_context", return_value="[参考1] 教材片段"), \
         patch.object(cg.sse_manager, "send_event", new=rec_event), \
         patch.object(cg.db, "execute", new=lambda *a, **k: None):
        await reading_agent.process("conn1", "sess_x", msg, {"chat_history": []})
    return cap, events


cap, events = asyncio.run(reading_run("推荐一些Python进阶的书"))
sys_prompt = cap["messages"][0]["content"]

sub_checks = [
    ("无残留占位符 {{", "{{" not in sys_prompt),
    ("知识水平已注入", "比较熟练" in sys_prompt),
    ("兴趣方向已归一化", "data_ai" in sys_prompt),
    ("易错点已注入", "闭包作用域" in sys_prompt),
    ("检索素材已注入", "[参考1]" in sys_prompt),
    ("话题清洗 → Python进阶", "当前主题：Python进阶" in sys_prompt),
    ("回复入库（session_id 已传）", cap["session_id"] == "sess_x"),
    ("SSE 声明资源类型 reading",
     any(n == "resource_start" and d.get("type") == "reading" for n, d in events)),
]
for label, ok in sub_checks:
    if not ok:
        fails.append(("ReadingAgent", label, "未通过"))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")

topic_cases = [("推荐一些Python进阶的书", "Python进阶"),
               ("有没有进阶的学习资料", "进阶"),
               ("有什么好书推荐", "Python进阶"),
               ("拓展阅读", "Python进阶"),
               ("推荐几本讲爬虫的书", "讲爬虫")]
print("  -- 话题清洗 --")
for msg, want in topic_cases:
    c, _e = asyncio.run(reading_run(msg))
    sysp = c["messages"][0]["content"]
    got = sysp.split("当前主题：")[1].split("\n")[0].strip() if "当前主题：" in sysp else "?"
    ok = got == want
    if not ok:
        fails.append((msg, want, got))
    print(f"  {'OK  ' if ok else 'FAIL'} {msg!r:24s} → 主题 {got!r} (期望 {want!r})")

print("\n" + ("全部通过 ✅" if not fails else f"失败 {len(fails)} 项: {fails}"))
sys.exit(1 if fails else 0)
