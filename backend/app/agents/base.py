"""智能体基类 — 含对话历史注入"""

import asyncio
import yaml
import os
from abc import ABC, abstractmethod
from config.settings import COURSE_CONFIG_PATH, ACTIVE_COURSE
from app.core.safety import safety_filter


class BaseAgent(ABC):
    """所有智能体的基类"""

    HISTORY_LIMIT = 20  # 默认注入最近20条历史

    def __init__(self, name: str, role_description: str = ""):
        self.name = name
        self.role_description = role_description
        self.prompts = self._load_prompts()

    def _load_prompts(self) -> dict:
        """加载当前课程的 Prompt 模板"""
        prompts_path = os.path.join(COURSE_CONFIG_PATH, ACTIVE_COURSE, "prompts.yaml")
        try:
            with open(prompts_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _get_system_prompt(self) -> str:
        """获取当前智能体的系统提示词"""
        return self.prompts.get(self.name, {}).get("system", "")

    def _build_messages(self, system_template: str, user_message: str, **kwargs) -> list[dict]:
        """构建 LLM 消息列表"""
        system_prompt = system_template
        for key, value in kwargs.items():
            system_prompt = system_prompt.replace(f"{{{{{key}}}}}", str(value))
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    # ================================================================
    # 对话历史注入
    # ================================================================

    def _build_messages_with_history(
        self,
        system_prompt: str,
        user_message: str,
        context: dict = None,
        history_limit: int = None,
    ) -> list[dict]:
        """构建带对话历史的消息列表

        结构: [system_prompt] + [历史消息...] + [user_message]

        Args:
            system_prompt: 系统提示词
            user_message: 当前用户消息
            context: 来自 orchestrator 的 context，含 chat_history
            history_limit: 最多注入多少条历史（默认 HISTORY_LIMIT）
        """
        limit = history_limit or self.HISTORY_LIMIT
        messages = [{"role": "system", "content": system_prompt}]

        # 注入对话历史
        history = (context or {}).get("chat_history", [])
        if history:
            # 取最近N条，且不包含当前消息（以防重复）
            recent = history[-limit:]
            for h in recent:
                # 跳过与当前用户消息相同的内容（去重）
                if h.get("role") == "user" and h.get("content") == user_message:
                    continue
                messages.append({"role": h["role"], "content": h["content"]})

        # 当前用户消息
        messages.append({"role": "user", "content": user_message})

        return messages

    # ================================================================
    # LLM 调用
    # ================================================================

    @abstractmethod
    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        """处理用户消息，通过 SSE 推送结果"""
        pass

    async def _stream_llm(
        self,
        conn_id: str,
        sse_manager,
        messages: list[dict],
        event_type: str = "content",
        max_tokens: int = 4096,
        session_id: str = None,
    ):
        """流式调用 LLM — 每个 chunk 到达立即推送，完成后自动保存到对话历史"""
        from app.core.llm_client import spark_llm

        full_text = ""
        async for chunk in spark_llm.chat_stream(messages, max_tokens=max_tokens):
            if chunk.get("error"):
                await sse_manager.send_event(conn_id, event_type, {
                    "agent": self.name, "type": "error",
                    "chunk": f"\n\n[错误] {chunk['error']}"
                })
                break
            content = chunk.get("content", "")
            # 输出脱敏：模型偶尔会复述上下文里的密钥串，展示给学生前先打码
            content = safety_filter.sanitize_output(content)
            if content:
                full_text += content
                await sse_manager.send_event(conn_id, event_type, {
                    "agent": self.name, "type": "text", "chunk": content
                })

        # 自动保存 AI 回复到对话历史
        if full_text and session_id:
            from app.db.sqlite_client import db
            try:
                db.execute(
                    "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, "assistant", full_text)
                )
            except Exception as e:
                print(f"[{self.name}] 保存回复失败: {e}")

        return full_text
