"""内容生成智能体 — 生成课程讲解文档、思维导图、拓展阅读（讯飞星火驱动）"""

import json
import re
import uuid
from app.agents.base import BaseAgent
from app.core import profile_utils, vocab
from app.core.sse_manager import sse_manager
from app.db.sqlite_client import db
from app.rag.retriever import retriever

# 用户消息里常见的引导语前缀（按长度降序逐个尝试剥掉）
_TOPIC_PREFIXES = [
    # 生成类请求（"给我生成一份 X 的学习讲义" → "X"）
    "再给我生成一份", "再生成一份", "重新生成一份", "重新生成",
    "给我生成一份", "给我生成", "生成一份", "生成一个", "生成",
    "帮我生成一份", "帮我生成一个", "帮我再生成一份", "帮我再生成",
    "再来一份", "再给我一份",
    "我想学习一下", "我想学习：", "我想学习:", "我想学习", "我想学一下", "我想学学",
    "我想学", "我想要学习", "我想要学", "我要学习", "我要学", "我学习", "我打算学",
    "帮我讲解一下", "帮我讲解", "帮我讲讲", "帮我讲一下", "帮我讲",
    "给我讲解一下", "给我讲解", "给我讲讲", "给我讲一下", "给我讲",
    "请帮我讲解", "请讲解", "请讲讲", "请讲一下",
    "帮我理解一下", "帮我理解", "帮我介绍一下", "帮我介绍",
    "帮我生成", "帮我整理", "帮我总结", "帮我写一份", "帮我写",
    "我想了解一下", "我想了解", "我想知道", "我想看看",
    "讲解一下", "讲解", "讲一讲", "讲一下", "讲讲",
    "解释一下", "解释", "介绍一下", "介绍",
    "什么是", "什么叫", "啥是", "教我一下", "教教我", "教我",
    "学习一下", "学习", "看看", "说说", "说一下",
]

# 尾部聊天尾巴（对标题毫无信息量）
_TOPIC_SUFFIXES = [
    # 生成物类型尾巴（"X 的学习讲义" → "X"）
    "的学习讲义", "学习讲义", "的思维导图", "思维导图",
    "的分层练习题", "分层练习题", "的练习题", "练习题",
    "的学习文档", "学习文档", "的学习资料", "拓展阅读", "阅读材料", "参考资料",
    "的资料", "的书", "书籍",
    "吗", "呢", "？", "?",
    "了解一点", "了解一下子", "了解一下", "了解下", "大概了解", "简单说说", "简单讲讲", "谢谢", "多谢",
]


def clean_topic(message: str, default: str = "Python基础") -> str:
    """从用户聊天原话中提取干净的主题名（用于资源标题与知识库检索）"""
    result = (message or "").strip()
    # 剥掉开头引导语（最长优先）
    for p in sorted(_TOPIC_PREFIXES, key=len, reverse=True):
        if result.startswith(p):
            result = result[len(p):]
            break
    # 剥掉结尾聊天尾巴
    for s in sorted(_TOPIC_SUFFIXES, key=len, reverse=True):
        if result.endswith(s):
            result = result[: -len(s)]
            break
    # 去掉首尾标点/空白
    result = result.strip(" ：:，,。.？?！!、\n\t ")
    # 截断过长输入（防止整段话进来当标题）
    if len(result) > 30:
        result = result[:30] + "…"
    return result or default


class ContentGenAgent(BaseAgent):
    """课程内容生成 — 完整输出"""

    def __init__(self):
        super().__init__("content_gen", "课程内容生成专家")

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        # 清洗话题：剥掉"我想学习："等引导语，只留知识点本身
        topic = clean_topic(message)
        profile = self._get_profile_summary(session_id)
        level = vocab.normalize_level(profile.get("knowledge_base", {}).get("level"))

        system_template = self._get_system_prompt()
        if not system_template:
            system_template = self._default_system_prompt()

        system_prompt = system_template.replace("{{knowledge_level}}", level)
        system_prompt = system_prompt.replace("{{learning_style}}", profile.get("learning_style", {}).get("type", "未知"))
        system_prompt = system_prompt.replace("{{error_patterns}}", json.dumps(profile.get("error_patterns", {}), ensure_ascii=False))
        system_prompt = system_prompt.replace("{{cognitive_level}}", self._bloom_str(profile))
        system_prompt = system_prompt.replace("{{topic}}", topic)
        system_prompt = system_prompt.replace("{{topic_context}}", f"Python程序设计 - {topic}")
        retrieved = retriever.retrieve_context(topic, profile)
        system_prompt = system_prompt.replace("{{retrieved_chunks}}",
            retrieved if retrieved else "（暂无相关知识库数据）")
        system_prompt = system_prompt.replace("{{avg_session_minutes}}", str(profile.get("learning_pace", {}).get("avg_session_minutes", 30)))

        doc_id = f"res_doc_{uuid.uuid4().hex[:8]}"
        # 资源标题取前20字做缩略名
        short_title = topic[:20] + ("…" if len(topic) > 20 else "")

        # 先告诉用户"在干嘛、要多久"：完整讲义要 40~60 秒才出第一个字，
        # 没有这行提示的话前端只有一个闪烁光标，用户会以为点了没反应。
        await sse_manager.send_event(conn_id, "thinking", {
            "agent": "content_gen",
            "status": f"正在为你生成《{short_title}》学习文档，大约需要 30~60 秒",
        })

        await sse_manager.send_event(conn_id, "resource_start", {
            "agent": "content_gen", "resource_id": doc_id, "type": "document",
            "title": f"{short_title} - 学习文档", "topic": topic,
        })

        messages = self._build_messages_with_history(
            system_prompt,
            f"用户想了解：{topic}\n请根据用户的需求生成一份完整的学习文档。",
            context
        )

        full_content = await self._stream_llm(
            conn_id, sse_manager, messages, event_type="content", session_id=session_id
        )

        db.execute(
            """INSERT INTO resources (id, session_id, type, title, topic, content, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, session_id, "document", f"{short_title} - 学习文档", topic, full_content,
             json.dumps({"difficulty": level, "estimated_minutes": 15, "word_count": len(full_content)}, ensure_ascii=False))
        )

        await sse_manager.send_event(conn_id, "resource_done", {
            "agent": "content_gen", "resource_id": doc_id, "type": "document", "status": "completed",
        })

    def _get_profile_summary(self, session_id: str) -> dict:
        # 画像按 user_id 存储，统一走 profile_utils（内部由 session 反查 user_id）
        return profile_utils.get_profile_summary_by_session(session_id)

    def _bloom_str(self, profile: dict) -> str:
        cl = profile.get("cognitive_level", {})
        if not isinstance(cl, dict):
            return "入门"
        # 画像里 cognitive_level 的键是中文（记忆/理解/应用/…）/历史英文值，
        # 排除 thinking_style 这类非数值字段
        vals = {}
        for k, v in cl.items():
            try:
                if float(v) > 0:
                    vals[k] = v
            except (TypeError, ValueError):
                continue
        if vals:
            return ", ".join(f"{k}={v}" for k, v in vals.items())
        return "入门"

    def _default_system_prompt(self) -> str:
        return """你是Python课程内容生成专家。基于学生画像生成个性化讲解文档。
输出标准Markdown格式，包含概念讲解、代码示例、易错点提醒和总结。"""


class MindmapAgent(BaseAgent):
    """思维导图生成"""

    def __init__(self):
        super().__init__("mindmap_gen", "知识可视化专家")

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        # 先剥掉"思维导图/导图/脑图"类词，再走通用话题清洗
        stripped = re.sub(r"(思维导图|导图|脑图|知识结构图|结构图)", "", message or "")
        topic = clean_topic(stripped)

        mm_id = f"res_mm_{uuid.uuid4().hex[:8]}"
        await sse_manager.send_event(conn_id, "resource_start", {
            "agent": "mindmap_gen", "resource_id": mm_id, "type": "mindmap",
            "title": f"{topic}思维导图", "topic": topic,
        })

        system_prompt = """你是知识可视化专家。生成Mermaid mindmap格式的思维导图。
要求：以主题为中心，展开3-4层分支（概念、语法、示例、注意），每个节点简洁（10字以内）。
只输出 ```mermaid ... ``` 代码块，不要其他文字。"""

        messages = self._build_messages_with_history(
            system_prompt,
            f"主题：{topic}",
            context
        )

        full_content = await self._stream_llm(
            conn_id, sse_manager, messages, event_type="content", session_id=session_id
        )

        db.execute(
            """INSERT INTO resources (id, session_id, type, title, topic, content, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mm_id, session_id, "mindmap", f"{topic}思维导图", topic, full_content,
             json.dumps({"format": "mermaid"}, ensure_ascii=False))
        )

        await sse_manager.send_event(conn_id, "resource_done", {
            "agent": "mindmap_gen", "resource_id": mm_id, "type": "mindmap", "status": "completed",
        })


class ReadingAgent(BaseAgent):
    """拓展阅读 — 基于画像推荐书籍 / 网站 / 项目

    历史遗留：本智能体早已注册（chat.py 里注册名 reading_gen），但 orchestrator 的
    INTENT_AGENT 里从来没有 "reading" 键，没有任何意图指向它 → 属于死代码，永远不会被调用。
    现已在 orchestrator 补上 reading 意图（描述 / 映射 / 强弱关键词 / 冷启动豁免）。
    """

    def __init__(self):
        super().__init__("reading_gen", "拓展阅读生成专家")

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        # 先剥掉"资源类型词 + 问答词 + 量词"，再走通用话题清洗：
        #   "推荐一些Python进阶的书" → "Python进阶"
        #   "有没有进阶的学习资料"   → "进阶"
        #   "有什么好书推荐"         → "书" → 落到默认主题
        stripped = re.sub(
            r"(拓展阅读|推荐阅读|阅读材料|参考资料|学习资料|学习资源|"
            r"有没有|有什么|有哪些|哪些|一些|一下|几本|几个|"
            r"好书|阅读|书籍|资料|推荐)",
            "", message or "")
        topic = clean_topic(stripped, default="Python进阶").strip("的 ")
        # 剥完只剩"书/资料"这类泛词时退回默认主题，避免拿单个字去检索
        if len(topic) < 2 or topic in ("书", "书籍", "好书", "资料", "阅读",
                                       "资源", "材料", "网站", "项目", "教程"):
            topic = "Python进阶"

        # 与其他内容类智能体一致：按 user_id 读画像 → 难度/兴趣真正影响推荐结果
        profile = self._get_profile_summary(session_id)
        level = vocab.normalize_level(profile.get("knowledge_base", {}).get("level"))
        interest = vocab.normalize_interest(
            profile.get("interest_tendency", {}).get("directions")
        ) or "未指定"

        system_template = self._get_system_prompt()
        if not system_template:
            system_template = self._default_system_prompt()

        system_prompt = system_template.replace("{{knowledge_level}}", level)
        system_prompt = system_prompt.replace(
            "{{learning_style}}", profile.get("learning_style", {}).get("type", "未知"))
        system_prompt = system_prompt.replace("{{interest}}", interest)
        system_prompt = system_prompt.replace(
            "{{error_patterns}}", json.dumps(profile.get("error_patterns", {}), ensure_ascii=False))
        system_prompt = system_prompt.replace("{{topic}}", topic)
        retrieved = retriever.retrieve_context(topic, profile)
        system_prompt = system_prompt.replace(
            "{{retrieved_chunks}}", retrieved if retrieved else "（暂无相关知识库数据）")

        rid = f"res_rd_{uuid.uuid4().hex[:8]}"
        short_title = topic[:20] + ("…" if len(topic) > 20 else "")

        # 同上：生成要几十秒，先把"在做什么、要多久"告诉用户
        await sse_manager.send_event(conn_id, "thinking", {
            "agent": "reading_gen",
            "status": f"正在按你的画像筛选《{short_title}》的拓展阅读，大约需要 30~60 秒",
        })

        await sse_manager.send_event(conn_id, "resource_start", {
            "agent": "reading_gen", "resource_id": rid, "type": "reading",
            "title": f"{short_title} - 拓展阅读", "topic": topic,
        })

        messages = self._build_messages_with_history(
            system_prompt,
            f"用户想了解：{topic}\n请推荐适合他的拓展阅读资源。",
            context,
        )

        full_content = await self._stream_llm(
            conn_id, sse_manager, messages, event_type="content", session_id=session_id
        )

        db.execute(
            """INSERT INTO resources (id, session_id, type, title, topic, content, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rid, session_id, "reading", f"{short_title} - 拓展阅读", topic, full_content,
             json.dumps({"format": "markdown", "difficulty": level,
                         "word_count": len(full_content)}, ensure_ascii=False))
        )

        await sse_manager.send_event(conn_id, "resource_done", {
            "agent": "reading_gen", "resource_id": rid, "type": "reading", "status": "completed",
        })

    def _get_profile_summary(self, session_id: str) -> dict:
        # 画像按 user_id 存储，统一走 profile_utils（内部由 session 反查 user_id）
        return profile_utils.get_profile_summary_by_session(session_id)

    def _default_system_prompt(self) -> str:
        return """你是Python学习资源推荐专家。基于学生画像推荐 3-5 个适合他的拓展阅读资源。
每个资源写清名称、类型、适合原因，附可访问链接（不确定就写搜索关键词，不要编造 URL）。
输出标准 Markdown 格式，末尾附建议阅读顺序。"""


content_gen_agent = ContentGenAgent()
mindmap_agent = MindmapAgent()
reading_agent = ReadingAgent()
