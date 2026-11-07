"""学习评估智能体 — 基于真实学习数据生成评估报告

修复记录（2026-10-03, P0）：
原先 evaluate 意图被映射到 content_gen，把"评估一下我的学习进展"当作
普通主题生成学习文档——报告里的数据是 LLM 凭空编造的。
现在：先复用 /api/evaluation 的统计逻辑从数据库算出真实数据，
再让 LLM 把真实数据组织成报告，并在提示词中明令禁止编造数字。
"""

import json
import uuid

from app.agents.base import BaseAgent
from app.core.sse_manager import sse_manager
from app.db.sqlite_client import db
from app.api.evaluation import get_evaluation, get_stats


class EvaluateAgent(BaseAgent):
    """学习评估 — 真实数据驱动的报告生成"""

    def __init__(self):
        super().__init__("evaluator", "学习评估专家")

    def _collect_real_data(self, session_id: str) -> dict:
        """从数据库收集真实学习数据（复用评估 API 的计算逻辑）"""
        evaluation = get_evaluation(session_id)
        stats = get_stats(session_id)
        return {
            "summary": evaluation.get("summary", ""),
            "dimensions": evaluation.get("dimensions", []),
            "adjustments": evaluation.get("adjustments", []),
            "stats": {k: v for k, v in stats.items() if k != "timeline"},
            "timeline": stats.get("timeline", []),
        }

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        # 1. 先算真实数据
        real_data = self._collect_real_data(session_id)

        # 2. 资源卡片
        report_id = f"res_eval_{uuid.uuid4().hex[:8]}"
        await sse_manager.send_event(conn_id, "resource_start", {
            "agent": "evaluator", "resource_id": report_id, "type": "document",
            "title": "学习评估报告", "topic": "学习评估",
        })

        # 3. LLM 只负责把真实数据写成报告，禁止编造数字
        system_prompt = """你是学习评估报告撰写专家。下面给你一份从数据库统计出的真实学习数据（JSON）。
请据此生成一份 Markdown 格式的学习评估报告。

铁律：
1. 报告中的每一个数字都必须来自给定数据，绝对不允许编造、修改或推算新数字；
2. 结构建议：总体概况 → 四个维度分析（知识掌握度/学习投入度/练习正确率/学习效率，各含得分与解读）→ 学习时间线 → 调整建议；
3. 如果数据几乎全为 0，就如实说明"还没有学习记录"，并给出起步建议（比如先生成学习路径、做几道练习题），不要美化也不要虚构；
4. 语言友善、面向学生，篇幅适中（400-600字）。

真实学习数据如下：
"""
        system_prompt += "```json\n" + json.dumps(
            real_data, ensure_ascii=False, default=str
        ) + "\n```"

        messages = self._build_messages_with_history(
            system_prompt,
            f"用户请求：{message}\n请基于系统提供的真实数据生成学习评估报告。",
            context,
        )

        full_content = await self._stream_llm(
            conn_id, sse_manager, messages, event_type="content", session_id=session_id
        )

        # 4. 存库（真实数据也存进 metadata，方便前端/回溯）
        db.execute(
            """INSERT INTO resources (id, session_id, type, title, topic, content, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (report_id, session_id, "document", "学习评估报告", "学习评估", full_content,
             json.dumps({"real_data": real_data, "source": "database"},
                        ensure_ascii=False, default=str))
        )

        await sse_manager.send_event(conn_id, "resource_done", {
            "agent": "evaluator", "resource_id": report_id, "type": "document", "status": "completed",
        })


evaluator_agent = EvaluateAgent()
