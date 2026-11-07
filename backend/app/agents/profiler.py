"""画像智能体 — 对话式学习画像构建（讯飞星火驱动）
两步法：1) 自然对话 → 2) 单独LLM调用提取JSON
"""

import json
import asyncio
from app.agents.base import BaseAgent
from app.core.sse_manager import sse_manager
from app.db.sqlite_client import db


class ProfilerAgent(BaseAgent):
    """通过对话构建学生画像"""

    # 列表型画像字段（库里单行存 JSON 数组）：写入时必须追加合并，不能覆盖
    LIST_FIELDS = {
        ("knowledge_base", "known_concepts"),
        ("learning_style", "preferred_formats"),
        ("interest_tendency", "directions"),
        ("error_patterns", "error_prone_topics"),
    }

    def __init__(self):
        super().__init__("profiler", "学习画像构建专家")

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        """对话式画像提取 — 两步法"""
        session_row = db.fetch_one("SELECT user_id FROM sessions WHERE id = ?", (session_id,))
        if not session_row:
            await sse_manager.send_event(conn_id, "content", {
                "agent": self.name, "type": "error", "chunk": "会话不存在"
            })
            return
        user_id = session_row["user_id"]

        # 1. 获取已有画像上下文
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

        all_dims = ["knowledge_base", "learning_style", "learning_goal",
                     "cognitive_level", "interest_tendency", "error_patterns", "learning_pace"]
        pending = [d for d in all_dims if d not in profile_context or not profile_context[d]]

        # === 第1步：自然对话（不要求JSON，保持良好UX）===
        system_template = self._get_system_prompt()
        if not system_template:
            system_template = self._default_chat_prompt()

        system_prompt = system_template.replace("{{current_profile}}", json.dumps(profile_context, ensure_ascii=False))
        system_prompt = system_prompt.replace("{{pending_dimensions}}", ", ".join(pending[:3]))
        system_prompt = system_prompt.replace("{{knowledge_graph_summary}}", "Python程序设计：变量→数据类型→控制流→函数→数据结构")

        # 使用带对话历史的消息列表
        messages = self._build_messages_with_history(system_prompt, message, context)

        chat_response = await self._stream_llm(
            conn_id, sse_manager, messages, event_type="content", session_id=session_id
        )

        # === 第2步：从对话中提取画像JSON（独立LLM调用）===
        if chat_response and len(chat_response) > 10:
            profile_data = await self._extract_profile_from_chat(message, chat_response, profile_context)
            if profile_data:
                await self._save_profile_data(profile_data, user_id, session_id, conn_id)

    async def _extract_profile_from_chat(self, user_msg: str, assistant_msg: str, existing: dict) -> list[dict]:
        """独立调用LLM，从对话中提取画像JSON（在线程池中运行，避免阻塞事件循环）"""
        from app.core.llm_client import spark_llm

        extraction_prompt = f"""你是学习画像数据提取器。根据以下对话，提取学生的学习特征，纯JSON数组输出。

已有画像：{json.dumps(existing, ensure_ascii=False)}

用户说：{user_msg}
助手回：{assistant_msg}

请从对话中提取所有可推断的画像特征。field必须严格使用以下标准名称：

- knowledge_base: level(只能取：零基础/了解一点/有基础/比较熟练), known_concepts(已知概念列表)
- learning_style: type(视频学习型/阅读文档型/动手项目型/刷题练习型), preferred_formats(偏好格式)
- learning_goal: primary(主要目标:通过考试/找工作面试/做个人项目/提升技能/学术研究), secondary(次要目标)
- cognitive_level: 记忆/理解/应用/分析/评价/创造, 各取0-100分值(根据回答的深度和准确性综合评估)
- interest_tendency: directions(兴趣方向，只能取：数据分析/AI、Web开发、游戏开发、自动化脚本、算法)
- error_patterns: error_prone_topics(易错主题)
- learning_pace: avg_session_minutes(单次学习分钟数), completion_speed(快/中等/慢)

只输出JSON数组，不要任何解释：
[
  {{\"dimension\":\"knowledge_base\",\"field\":\"level\",\"value\":\"了解一点\",\"confidence\":0.9,\"evidence\":\"用户说只学过一点Python\"}},
  {{\"dimension\":\"learning_style\",\"field\":\"type\",\"value\":\"动手项目型\",\"confidence\":0.85,\"evidence\":\"用户说习惯动手做项目\"}}
]

如果没有可提取的新特征，输出：[]"""

        loop = asyncio.get_event_loop()

        def _call_sync():
            return spark_llm.chat_sync(
                [{"role": "user", "content": extraction_prompt}],
                temperature=0.3,
                max_tokens=1024,
            )

        try:
            result = await loop.run_in_executor(None, _call_sync)
            return self._try_parse_json_array(result)
        except Exception as e:
            print(f"[Profiler] 提取失败: {e}")
            return None

    @staticmethod
    def _try_parse_json_array(text: str) -> list[dict] | None:
        """从LLM输出中提取JSON数组"""
        import re
        # 尝试直接解析
        text = text.strip()
        if text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # 从 ```json ... ``` 块提取
        match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 从文本中找 JSON 数组
        match = re.search(r'\[[\s\S]*\{[\s\S]*"dimension"[\s\S]*\}[\s\S]*\]', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        print(f"[Profiler] 无法解析JSON: {text[:300]}")
        return None

    @staticmethod
    def _normalize_value(raw) -> str:
        """把画像值统一成可入库的字符串。

        LLM 对 known_concepts / directions / error_prone_topics 这类字段
        会返回数组。若直接 str()，会得到 "['Java']" 这种 Python 字面量，
        读取端再把它当作单个元素包一层，最终显示成 ["['Java']"]。
        这里统一序列化为 JSON 数组，读取端用 _parse_list_value() 还原。
        """
        if isinstance(raw, (list, dict)):
            return json.dumps(raw, ensure_ascii=False)
        return str(raw)

    async def _save_profile_data(self, data: list[dict], user_id: str, session_id: str, conn_id: str):
        """保存画像数据到数据库并推送SSE

        必须走 profile_utils（画像写入唯一入口）：
        · 标量字段 → upsert（覆盖式更新）
        · 列表字段 → append_list（追加去重）。历史实现用覆盖式 upsert，
          而后台静默分析一返回就会把累计的 known_concepts 整个替换掉。
        """
        from app.core import profile_utils

        for item in data:
            dim = item.get("dimension", "")
            field = item.get("field", "")
            value = self._normalize_value(item.get("value", ""))
            confidence = float(item.get("confidence", 0.7))
            evidence = item.get("evidence", "")

            if not dim or not field or not value:
                continue

            try:
                if (dim, field) in self.LIST_FIELDS:
                    items = self._parse_list_value(value)
                    if not items:
                        continue
                    profile_utils.append_list(
                        user_id, session_id, dim, field, items, confidence, evidence
                    )
                else:
                    profile_utils.upsert(
                        user_id, session_id, dim, field, value, confidence, evidence
                    )
            except Exception as e:
                print(f"[Profiler] 保存失败: {e}")
                continue

            await sse_manager.send_event(conn_id, "profile", {
                "dimension_updated": dim,
                "field": field,
                "value": value,
                "confidence": confidence,
                "evidence": evidence,
            })

    @staticmethod
    def _parse_list_value(value: str) -> list:
        """把列表型字段的值还原成 list[str]（读取端统一存 JSON 数组）"""
        try:
            parsed = json.loads(value)
        except Exception:
            return [value] if value else []
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x not in (None, "")]
        return [str(parsed)] if parsed not in (None, "") else []

    def _default_chat_prompt(self) -> str:
        return """你是学习画像构建专家。通过自然对话了解学生的背景和目标。

对话规则：
1. 每次只探索1-2个维度，不要连续提问
2. 从学生回答中推断特征，对话流畅自然
3. 发现与已有画像矛盾时友善确认

待了解维度：knowledge_base（知识基础）、learning_style（学习风格）、learning_goal（学习目标）、
cognitive_level（认知水平）、interest_tendency（兴趣方向）、error_patterns（易错点）、learning_pace（学习节奏）

已知画像：{{current_profile}}
待探索：{{pending_dimensions}}
课程：{{knowledge_graph_summary}}

请自然回应用户，像朋友聊天一样了解他们的学习情况。"""

    def _default_system_prompt(self) -> str:
        return self._default_chat_prompt()


profiler_agent = ProfilerAgent()
