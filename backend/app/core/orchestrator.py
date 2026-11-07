"""协调智能体 — 意图识别与任务分发 + 对话历史管理"""

import asyncio
import json
import re
import numpy as np
from app.core.sse_manager import sse_manager
from app.core.safety import safety_filter
from app.db.sqlite_client import db

# 聊天内自述"学完了"的匹配：覆盖 学习完了/学习好了/学好了/学习完成/学完了/看完了/学会了/掌握了/搞定了/完成了 等
# 设计成"学/看/听/做 + 完/好"与"完成/搞定/掌握/学会"两大类通用模式，避免遗漏用户各种口语说法
_COMPLETION_RE = re.compile(
    r"((学|看|听|做)(习)?(完|好)|完成|搞定|掌握|学会)"
)
# 排除请求类语句（"帮我完成XX代码"不是自述完成）
_REQUEST_RE = re.compile(r"帮我|给我|请|出题|生成|写一|实现|做一个|做个")

# 明确的学习请求："我想学习X / 教我X / 给我讲讲X"这类点名要学知识点的表述。
# 冷启动阶段也不劫持这些请求——直接开教，画像由后台静默分析继续收集。
_LEARN_REQUEST_RE = re.compile(
    r"我想学习|我想学一下|我想学|教我|给我讲|讲讲|讲解一下|什么是|"
    r"怎么用|怎么实现|介绍一下|解释一下|帮我理解|了解一下"
)


class IntentClassifier:
    """基于 Embedding 语义相似度的意图分类器

    优先用讯飞 Embedding 做语义匹配，不可用时回退到关键词。
    """

    # 意图的自然语言描述（用于 embedding 相似度计算）
    # 描述关键词要尽量区分，避免语义重叠
    INTENT_DESCRIPTIONS = {
        "profile": "自我介绍：我的编程基础是零基础、之前学过Java、我有C语言基础。"
                   "我的学习目标是考试、找工作、做项目。我每天能学1小时。"
                   "我喜欢看视频学习、动手做项目、刷题练习。",
        "learn": "我想学新知识：for循环怎么用、什么是列表推导式、装饰器是什么、"
                 "介绍一下面向对象、Python字典的用法、文件读写怎么操作。"
                 "教我某个知识点、给我讲解某个概念、帮我理解某个技术。",
        "mindmap": "我要思维导图：生成for循环的思维导图、画一个Python基础知识的脑图、"
                   "帮我梳理面向对象的知识结构图、做个知识框架的导图。",
        "reading": "我要拓展阅读资源：推荐一些Python学习书籍、有什么好书可以看、"
                   "推荐几个学习网站、推荐可以练手的开源项目、有没有进阶的学习资料、"
                   "想再深入学点该看什么、推荐一下阅读材料。",
        "practice": "我要做题练习：给我出几道循环的练习题、来一套Python测验题、"
                    "出几道关于列表的考题、考试测试一下。",
        "code": "我要写代码做项目：帮我写一个爬虫、帮我爬取网站数据、"
                "写个爬虫抓取租房价格、做一个计算器项目、开发一个小程序、"
                "给个代码示例看看、编程实现一个功能、帮我实现一个需求、"
                "写个脚本自动处理、帮我开发一个工具。",
        "path": "我要学习路线规划：下一步学什么、帮我规划Python学习路径、"
                "安排一个学习计划、推荐学习顺序。",
        "ask": "我遇到问题求助：为什么代码报错了、这个TypeError怎么改、"
               "程序运行结果不对怎么办、帮我看看这段代码哪里有问题、"
               "这个错误是什么意思。",
        "evaluate": "我要看学习评估报告：评估我的Python水平、我的学习进展怎么样、"
                    "生成一份学习报告、看看我学得如何。",
    }

    # 意图 → 智能体名 映射
    INTENT_AGENT = {
        "profile": "profiler",
        "learn": "content_gen",
        "mindmap": "mindmap_gen",
        "reading": "reading_gen",
        "practice": "quiz_gen",
        "code": "code_agent",
        "path": "path_planner",
        "ask": "tutor",
        "evaluate": "evaluator",
    }

    def __init__(self):
        self._intent_embeddings: dict[str, np.ndarray] = {}
        self._initialized = False

    def _ensure_initialized(self):
        """延迟初始化：首次使用时批量计算所有意图描述的 embedding"""
        if self._initialized:
            return
        try:
            from app.rag.embedder import spark_embedder
            for intent, desc in self.INTENT_DESCRIPTIONS.items():
                vec = spark_embedder.embed_query(desc)
                if vec and any(v != 0 for v in vec):
                    self._intent_embeddings[intent] = np.array(vec, dtype=np.float32)
            if self._intent_embeddings:
                print(f"[IntentClassifier] 已初始化 {len(self._intent_embeddings)} 个意图向量")
        except Exception as e:
            print(f"[IntentClassifier] 初始化失败，将使用关键词回退: {e}")
        self._initialized = True

    def classify(self, message: str, min_similarity: float = 0.25) -> tuple[str, float]:
        """返回 (intent, similarity_score)

        若 embedding 不可用或最高相似度低于阈值，返回 ("", 0.0)，由调用方回退关键词。
        """
        self._ensure_initialized()
        if not self._intent_embeddings:
            return ("", 0.0)

        try:
            from app.rag.embedder import spark_embedder
            msg_vec = spark_embedder.embed_query(message)
        except Exception:
            return ("", 0.0)

        if not msg_vec or all(v == 0 for v in msg_vec):
            return ("", 0.0)

        msg_vec = np.array(msg_vec, dtype=np.float32)
        scores = []
        for intent, intent_vec in self._intent_embeddings.items():
            score = self._cosine_similarity(msg_vec, intent_vec)
            scores.append((score, intent))
        scores.sort(reverse=True, key=lambda x: x[0])

        if not scores or scores[0][0] < min_similarity:
            return ("", scores[0][0] if scores else 0.0)

        # 歧义检测：top-2 分数差 < 0.015 时回退关键词，避免误判
        if len(scores) >= 2 and (scores[0][0] - scores[1][0]) < 0.015:
            return ("", scores[0][0])

        return (scores[0][1], scores[0][0])

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        dot = float(np.dot(a, b))
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class Orchestrator:
    """协调器：解析用户意图，调度子智能体，管理对话上下文记忆"""

    # 关键词回退（Embedding 不可用或相似度过低时使用）
    INTENT_KEYWORDS = {
        "profile": ["画像", "了解我", "我的水平", "我的基础", "我的情况",
                    "学过", "零基础", "经验", "我学过", "我的目标"],
        "mindmap": ["思维导图", "导图", "脑图", "知识图谱", "结构图"],
        # reading 必须排在 learn 前面：弱关键词是"按字典顺序取首个命中"，
        # 而 "学习资料"/"学习资源" 里都含 learn 的 "学习"，learn 排在前面会把
        # 资源推荐类请求抢走，去生成一份讲义。
        "reading": ["拓展阅读", "推荐阅读", "推荐资料", "推荐一些资料", "推荐几本",
                    "推荐网站", "推荐项目", "学习资源", "学习资料推荐", "阅读材料",
                    "有什么书", "看什么书", "该看什么", "进阶资料"],
        "practice": ["练习", "题目", "做题", "测验", "测试", "考题", "出题", "出几道"],
        "code": ["编程", "实操", "案例", "写一个", "代码实操", "写代码", "帮我写", "做一个"],
        "path": ["路径", "计划", "下一步", "学习路线", "规划"],
        "ask": ["为什么", "报错", "错误", "不会", "怎么办", "怎么改"],
        "evaluate": ["评估", "报告", "进展", "学得怎么样", "效果"],
        "learn": ["学习", "教我", "讲解", "什么是", "怎么用", "介绍一下", "了解",
                  "讲讲", "讲一下", "说说", "说一下", "解释", "原理", "教我一下",
                  "帮我理解", "怎么实现"],
    }

    HISTORY_LIMIT = 20  # 注入LLM的历史消息条数

    def __init__(self):
        self.agents = {}
        self.intent_classifier = IntentClassifier()

    def register_agent(self, name: str, agent):
        """注册子智能体"""
        self.agents[name] = agent

    # 强信号关键词：只要命中就必须匹配该意图，无视 Embedding 结果
    # 注意：不要放模糊词（如"做一个"会被"做一个练习题"触发 → 误判为 code）
    STRONG_KEYWORDS: dict[str, list[str]] = {
        # reading — 只放"单独出现就能定性"的短语；带动词的说法（"推荐几本书"）
        # 由 detect_intent 里的 _READING_RE 处理，不必在这里穷举。
        "reading": ["拓展阅读", "推荐阅读", "阅读材料", "参考资料", "学习资源推荐"],
        # code — 要求写代码/做项目（全部都指向代码产物）
        "code": ["帮我写", "写一个", "写个", "写段", "写代码",
                 "帮我开发", "爬虫", "代码实操", "编程实现", "写段代码"],
        # mindmap — 可视化脑图
        "mindmap": ["思维导图", "导图", "脑图", "知识图谱"],
        # practice — 做题/测验
        "practice": ["出几道", "出题", "做题", "测验", "练习题", "给我出"],
        # path — 学习规划
        "path": ["学习路线", "学习路径", "学习计划"],
        # evaluate — 评估报告
        # 注意: "评估" 必须放在强信号里。profile 的关键词表里也有 "评估" 相关词，
        # 而弱关键词是按字典顺序取首个命中，profile 排在 evaluate 前面，
        # 不提升为强信号的话 evaluate 意图永远无法命中。
        "evaluate": ["学得怎么样", "评估报告", "评估", "学习进展", "学习报告", "学习评估"],
        # learn — 明确点名学知识点（前端"开始学习"跳转固定发"我想学习：X"）
        "learn": ["我想学习", "我想学一下", "教我"],
    }

    # 拓展阅读专用规则：**先索取动词、后资源名词**在同一小句内同时出现。
    # 为什么不只用固定短语：用户的说法太多（"推荐一些Python进阶的书"、
    # "有没有进阶的学习资料"、"推荐几个练手的开源项目"、"有什么好书推荐"），
    # 短语表怎么列都列不全；而「动词 + 名词」两个词表组合能覆盖绝大多数说法。
    # 为什么要求先后顺序：避免「我这个项目有没有bug」这类"名词在前、动词在后"
    # 的排错请求被误判为要资源。
    _READING_RE = re.compile(
        r"(推荐|有什么|有没有|哪些|看什么|该看|值得看|求推荐)"
        r"[^，。！？；\n]{0,15}?"
        r"(书籍|书|资料|资源|网站|项目|教程|读物)"
    )

    def detect_intent(self, message: str) -> str:
        """意图检测：拓展阅读规则 → 强信号关键词 → Embedding 语义 → 关键词回退 → 默认 ask"""
        # 0) 拓展阅读：必须在强信号之前判。code 的强信号里有"爬虫"这类宽泛词，
        #    「推荐几本讲爬虫的书」会被抢去写代码，而用户其实是要书单。
        if self._READING_RE.search(message):
            print(f"[Orchestrator] 拓展阅读规则命中（资源名词 + 索取动词）")
            return "reading"

        # 1) 强信号关键词 — 绝对优先，无视 Embedding
        keyword_intent = self._match_keywords(message, self.STRONG_KEYWORDS)
        if keyword_intent:
            print(f"[Orchestrator] 强信号关键词: {keyword_intent}")
            return keyword_intent

        # 2) Embedding 语义匹配
        intent, score = self.intent_classifier.classify(message)
        if intent:
            # 2.5) 反向检查：Embedding 结果是否和弱关键词冲突
            weak_intent = self._match_keywords(message, self.INTENT_KEYWORDS)
            if weak_intent and weak_intent != intent:
                print(f"[Orchestrator] 关键词覆盖 Embedding: {weak_intent} (Embedding 原为 {intent})")
                return weak_intent
            print(f"[Orchestrator] Embedding 匹配: {intent} (相似度 {score:.3f})")
            return intent

        # 3) Embedding 失败 → 回退弱关键词
        weak_intent = self._match_keywords(message, self.INTENT_KEYWORDS)
        if weak_intent:
            return weak_intent

        # 4) 无匹配 → 走 tutor 自然对话
        return "ask"

    @staticmethod
    def _match_keywords(message: str, keyword_map: dict) -> str | None:
        """在 keyword_map 中查找匹配，返回第一个命中的意图"""
        for intent_kw, keywords in keyword_map.items():
            for kw in keywords:
                if kw in message:
                    print(f"[Orchestrator] 关键词匹配: {intent_kw} ← \"{kw}\"")
                    return intent_kw
        return None

    def _count_profile_dimensions(self, session_id: str) -> int:
        """统计当前会话已构建的画像维度数"""
        try:
            row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
            if not row:
                return 0
            rows = db.fetch_all(
                "SELECT COUNT(DISTINCT dimension) as cnt FROM profiles WHERE user_id = ?",
                (row["user_id"],)
            )
            return rows[0]["cnt"] if rows else 0
        except Exception:
            return 0

    # ================================================================
    # 对话历史管理
    # ================================================================

    def save_message(self, session_id: str, role: str, content: str):
        """保存一条消息到对话历史"""
        try:
            db.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content)
            )
        except Exception as e:
            print(f"[Orchestrator] 保存消息失败: {e}")

    def load_history(self, session_id: str, limit: int = None) -> list[dict]:
        """加载会话的最近N条对话历史"""
        if limit is None:
            limit = self.HISTORY_LIMIT
        try:
            rows = db.fetch_all(
                """SELECT role, content FROM chat_messages
                   WHERE session_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (session_id, limit)
            )
            # 反转回时间正序
            rows.reverse()
            return [{"role": r["role"], "content": r["content"]} for r in rows]
        except Exception as e:
            print(f"[Orchestrator] 加载历史失败: {e}")
            return []

    # ================================================================
    # 消息处理
    # ================================================================

    async def handle_message(self, conn_id: str, session_id: str, message: str, context: dict = None):
        """处理用户消息，分发到子智能体（含对话历史注入）"""
        if context is None:
            context = {}

        # 0. 输入安全：提示注入 / 越狱防护
        #    命中时不调用大模型（避免被诱导输出角色设定原文），直接给友好引导。
        #    该模块此前定义了却从未被调用，属于"有护栏没接线"。
        allowed, reason = safety_filter.check_input(message)
        if not allowed:
            print(f"[Orchestrator] 输入安全拦截: {reason}")
            reply = ("我是你的 Python 学习助手，专心陪你学编程 😊\n\n"
                     "刚才那句话我回答不了，换个问法吧 —— 比如：\n"
                     "- 「给我讲讲 Python 的循环」\n"
                     "- 「这段代码为什么报错」\n"
                     "- 「帮我出几道列表的练习题」")
            self.save_message(session_id, "user", message)
            self.save_message(session_id, "assistant", reply)
            await sse_manager.send_event(conn_id, "content", {
                "agent": "safety", "type": "text", "chunk": reply,
            })
            await sse_manager.send_event(conn_id, "done", {
                "session_id": session_id,
                "intent": "blocked",
                "profile_updated": False,
                "path_completed": None,
            })
            return

        intent = self.detect_intent(message)

        # 自述"学完了/学习好了"这类完成语句：真实意图是汇报进度而非学新知识，
        # 严禁走 content_gen 生成《学习好了 - 学习文档》这类无意义讲义 → 统一转 tutor 简单回应
        if intent in ("learn", "mindmap", "reading") and len(message) <= 30 \
                and _COMPLETION_RE.search(message) and not _REQUEST_RE.search(message):
            print(f"[Orchestrator] 完成类自述拦截: 原意图 {intent} → ask")
            intent = "ask"

        # 画像冷启动：如果画像维度不足3个，非明确问答的消息优先走 profiler。
        # 豁免：ask/code/practice/evaluate/reading 与画像无关；明确的 learn 请求（"我想学习X"）
        # 直接开教——想学却不教的体验错位比画像不完整更伤，画像由每5条消息的
        # 后台静默分析继续收集。
        # 注意：evaluate 依赖 learning_records/learning_paths 的真实数据，必须豁免；
        #       reading 是"要资料"的明确请求，被画像问卷劫持同样错位（缺画像时按默认档推荐即可）。
        profile_count = self._count_profile_dimensions(session_id)
        if profile_count < 3:
            if intent == "learn" and _LEARN_REQUEST_RE.search(message):
                print(f"[Orchestrator] 冷启动但为明确学习请求，直接开教")
            elif intent not in ("ask", "code", "practice", "evaluate", "reading"):
                intent = "profile"

        # 1. 保存用户消息
        self.save_message(session_id, "user", message)

        # 1.5 自述完成检测（服务端兜底）：用户说"学完了/学习完了/完成了"等，
        #     自动把最近在学的主题（聊天记录里最后一条"我想学习：X"）记入学习进度。
        #     不依赖前端状态，刷新/重新登录后依然有效。
        completed_topic = None
        if len(message) <= 30 and _COMPLETION_RE.search(message) and not _REQUEST_RE.search(message):
            completed_topic = self._mark_recent_topic_completed(session_id) or None
        context["path_completed_topic"] = completed_topic

        # 2. 加载对话历史，注入 context
        history = self.load_history(session_id)
        context["chat_history"] = history

        # 3. thinking 事件
        await sse_manager.send_event(conn_id, "thinking", {
            "agent": "orchestrator",
            "status": f"正在分析你的需求...（识别意图: {intent}）"
        })

        # 4. 根据意图调度
        agent_name = self.intent_classifier.INTENT_AGENT.get(intent, "content_gen")
        agent = self.agents.get(agent_name)
        if agent:
            await agent.process(conn_id, session_id, message, context)

        # 5. 后台静默画像分析（每5条消息触发一次，不影响用户体验）
        msg_count = self._count_messages(session_id)
        if msg_count % 5 == 0 and msg_count > 0:
            asyncio.create_task(self._background_profile(session_id))

        # 6. done 事件
        await sse_manager.send_event(conn_id, "done", {
            "session_id": session_id,
            "intent": intent,
            "profile_updated": intent == "profile",
            "path_completed": completed_topic,
        })

    def _recent_learning_topic(self, session_id: str) -> str:
        """从聊天记录里找最近一次"我想学习：X"的主题名"""
        try:
            row = db.fetch_one(
                "SELECT content FROM chat_messages WHERE session_id = ? AND role = 'user' "
                "AND content LIKE %s ORDER BY created_at DESC LIMIT 1",
                (session_id, "我想学习%"),
            )
            if not row:
                return ""
            m = re.match(r"我想学习[:：]?\s*(.+)", row["content"] or "")
            return m.group(1).strip() if m else ""
        except Exception:
            return ""

    def _mark_recent_topic_completed(self, session_id: str) -> str:
        """把最近在学的主题标记为已完成，返回主题名；无需记录时返回空串"""
        try:
            topic = self._recent_learning_topic(session_id)
            if not topic:
                return ""
            row = db.fetch_one(
                "SELECT path_json FROM learning_paths WHERE session_id = ?", (session_id,)
            )
            if not row:
                return ""
            path_data = json.loads(row["path_json"] or "{}")
            exists = False
            for phase in path_data.get("phases", []):
                for t in phase.get("topics", []):
                    if t.get("title") == topic or t.get("topic_id") == topic:
                        exists = True
                        if t.get("status") == "completed":
                            return ""  # 已记过，不重复记
            if not exists:
                return ""  # 主题不在学习路径里（如闲聊话题），不记
            from app.api.learning_path import complete_topic
            from app.models.learning_path import CompleteTopicRequest
            complete_topic(session_id, CompleteTopicRequest(
                topic=topic, resource_id="", time_spent_minutes=0,
                self_evaluation="聊天中自述完成",
            ))
            return topic
        except Exception as e:
            print(f"[orchestrator] 记录学习进度失败: {e}")
            return ""

    def _count_messages(self, session_id: str) -> int:
        """统计会话消息数"""
        try:
            row = db.fetch_one(
                "SELECT COUNT(*) as cnt FROM chat_messages WHERE session_id = ?",
                (session_id,)
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0

    async def _background_profile(self, session_id: str):
        """后台任务：从最近对话中静默提取画像数据"""
        try:
            from app.agents.profiler import profiler_agent

            # 获取 user_id 和已有画像
            session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
            if not session_row:
                return
            user_id = session_row["user_id"]

            existing = db.fetch_all(
                "SELECT dimension, field, value, confidence FROM profiles WHERE user_id = ?",
                (user_id,)
            )
            profile_context = {}
            for row in existing:
                dim = row["dimension"]
                if dim not in profile_context:
                    profile_context[dim] = {}
                profile_context[dim][row["field"]] = row["value"]

            # 加载最近4条对话
            recent = self.load_history(session_id, limit=4)
            if len(recent) < 2:
                return

            # 合并为一段对话文本供提取
            user_msgs = [m["content"] for m in recent if m["role"] == "user"]
            asst_msgs = [m["content"] for m in recent if m["role"] == "assistant"]

            if not user_msgs or not asst_msgs:
                return

            user_text = " ".join(user_msgs[-2:])   # 最近2条用户消息
            asst_text = " ".join(asst_msgs[-2:])    # 最近2条AI回复

            # 调用 profiler 的提取逻辑
            profile_data = await profiler_agent._extract_profile_from_chat(
                user_text, asst_text, profile_context
            )

            if profile_data:
                await profiler_agent._save_profile_data(profile_data, user_id, session_id, None)
                print(f"[Orchestrator] 后台画像更新: {len(profile_data)} 条新数据")

        except Exception as e:
            print(f"[Orchestrator] 后台画像分析失败: {e}")


# 全局协调器
orchestrator = Orchestrator()
