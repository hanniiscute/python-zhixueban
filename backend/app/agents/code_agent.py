"""代码智能体 — 生成代码实操案例（Jupyter Notebook格式，讯飞星火驱动）"""

import json
import uuid
from app.agents.base import BaseAgent
from app.core import profile_utils, vocab
from app.core.sse_manager import sse_manager
from app.db.sqlite_client import db


class CodeAgent(BaseAgent):
    """代码实操案例生成"""

    def __init__(self):
        super().__init__("code_agent", "代码实操教学专家")

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        # 直接用用户原始消息作为需求描述，让 LLM 自行理解
        topic = message.strip()
        profile = self._get_profile_summary(session_id)

        system_template = self._get_system_prompt()
        if not system_template:
            system_template = self._default_system_prompt()

        system_prompt = system_template.replace("{{knowledge_level}}", vocab.normalize_level(profile.get("knowledge_base", {}).get("level")))
        system_prompt = system_prompt.replace("{{learning_style}}", profile.get("learning_style", {}).get("type", "未知"))
        system_prompt = system_prompt.replace("{{topic}}", topic)
        system_prompt = system_prompt.replace("{{error_patterns}}", json.dumps(profile.get("error_patterns", {}), ensure_ascii=False))

        nb_id = f"res_nb_{uuid.uuid4().hex[:8]}"
        short_title = topic[:20] + ("…" if len(topic) > 20 else "")

        await sse_manager.send_event(conn_id, "resource_start", {
            "agent": "code_agent", "resource_id": nb_id, "type": "notebook",
            "title": f"{short_title} - 代码案例", "topic": topic,
        })

        messages = self._build_messages_with_history(
            system_prompt,
            f"用户需求：{topic}\n请根据用户需求生成代码案例。⚠️ 必须用纯 Markdown 格式，严禁输出 JSON 或 {{}} 结构。代码用 ```python 代码块包裹。",
            context
        )

        full_content = await self._stream_llm(
            conn_id, sse_manager, messages, event_type="content", session_id=session_id
        )

        # 将 Markdown 转为 notebook 格式存储
        notebook = self._md_to_notebook(full_content, topic)

        db.execute(
            """INSERT INTO resources (id, session_id, type, title, topic, content, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (nb_id, session_id, "notebook", f"{short_title} - 代码案例", topic,
             json.dumps(notebook, ensure_ascii=False),
             json.dumps({"format": "ipynb", "cell_count": len(notebook.get("cells", []))}, ensure_ascii=False))
        )

        await sse_manager.send_event(conn_id, "resource_done", {
            "agent": "code_agent", "resource_id": nb_id, "type": "notebook", "status": "completed",
        })

    def _get_profile_summary(self, session_id: str) -> dict:
        # 画像按 user_id 存储，统一走 profile_utils（内部由 session 反查 user_id）
        return profile_utils.get_profile_summary_by_session(session_id)

    def _md_to_notebook(self, text: str, topic: str) -> dict:
        """将 Markdown 文本转为 Jupyter Notebook 格式（用于资源存储）"""
        import re
        cells = []
        # 按 ## 标题分割段落
        sections = re.split(r'\n(?=## )', text.strip())
        # 如果开头没有 ##，第一段作为 markdown cell
        if sections and not sections[0].startswith('##'):
            sections.insert(0, '')

        first = True
        for i, section in enumerate(sections):
            if not section.strip():
                continue
            # 找到代码块和文本的边界
            code_blocks = list(re.finditer(r'```python\s*\n(.*?)```', section, re.DOTALL))
            code_positions = [(m.start(), m.end(), m.group(1)) for m in code_blocks]

            if not code_positions:
                # 纯 markdown cell
                source = section.strip() if not first else section.strip()
                if source:
                    cells.append({"cell_type": "markdown", "metadata": {}, "source": [source]})
            else:
                # 混合：先取代码前的文字，再取代码，再取代码后的文字
                prev_end = 0
                for start, end, code in code_positions:
                    text_before = section[prev_end:start].strip()
                    if text_before:
                        cells.append({"cell_type": "markdown", "metadata": {}, "source": [text_before]})
                    cells.append({"cell_type": "code", "metadata": {}, "source": [code.rstrip()], "outputs": []})
                    prev_end = end
                text_after = section[prev_end:].strip()
                if text_after:
                    cells.append({"cell_type": "markdown", "metadata": {}, "source": [text_after]})
            first = False

        return {
            "nbformat": 4, "nbformat_minor": 5,
            "metadata": {"title": f"{topic}代码实操"},
            "cells": cells or [{"cell_type": "markdown", "source": [text]}],
        }

    def _default_system_prompt(self) -> str:
        return """你是Python代码专家。根据用户需求生成可直接运行的代码，用 Markdown 格式输出。

⚠️ 严禁输出 JSON 格式、严禁输出 {} 结构、严禁输出 ipynb。

## 输出结构
1. **场景说明** — 代码解决什么问题
2. **完整代码** — ```python 代码块，关键行加中文注释
3. **运行说明** — 如何运行、依赖库（含 pip install 命令）
4. **关键点解析** — 核心技巧或易错点

## 要求
- 代码完整可运行，不要留 TODO 让学生补全
- 注释精准，不过度注释
- 涉及第三方库时标明安装命令"""


code_agent = CodeAgent()
