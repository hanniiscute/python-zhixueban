"""路径规划 + 智能辅导智能体（讯飞星火驱动）"""

import json
import uuid
import os
from app.agents.base import BaseAgent
from app.core import profile_utils
from app.core.sse_manager import sse_manager
from app.db.sqlite_client import db
from app.rag.retriever import retriever
from config.settings import COURSE_CONFIG_PATH, ACTIVE_COURSE


class PathPlannerAgent(BaseAgent):
    """学习路径规划"""

    def __init__(self):
        super().__init__("path_planner", "学习路径规划专家")

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        # 加载学习路径知识库（4条路径，51个知识点）
        lps = self._load_learning_paths()
        profile = self._get_profile_summary(session_id)
        completed = self._get_completed_topics(session_id)

        system_template = self._get_system_prompt()
        if not system_template:
            system_template = self._default_system_prompt()

        system_prompt = system_template.replace("{{knowledge_graph}}", json.dumps(lps, ensure_ascii=False, indent=2))
        system_prompt = system_prompt.replace("{{profile}}", json.dumps(profile, ensure_ascii=False, indent=2))
        system_prompt = system_prompt.replace("{{completed_topics}}", json.dumps(completed, ensure_ascii=False))
        system_prompt = system_prompt.replace("{{learning_pace}}", profile.get("learning_pace", {}).get("completion_speed", "中等"))

        path_id = f"path_{uuid.uuid4().hex[:8]}"

        messages = self._build_messages_with_history(
            system_prompt,
            "请根据我的画像和知识图谱，规划个性化的Python学习路径，输出JSON格式",
            context
        )

        full_response = await self._stream_llm(
            conn_id, sse_manager, messages, event_type="content", session_id=session_id
        )

        # 尝试解析路径JSON
        path_data = self._try_parse_path(full_response, lps)

        # ── 保留学习进度 ──
        # LLM 重新生成的路径里不含 in_progress / completed 状态（默认全 available/locked），
        # 直接覆盖写回会把用户已经学完的主题清空。这里按主题标题把旧状态合并回来，
        # 并复用原有 path_id（learning_paths.session_id 是唯一键）。
        existing = db.fetch_one(
            "SELECT id, path_json FROM learning_paths WHERE session_id = ?", (session_id,)
        )
        if existing:
            try:
                old_data = json.loads(existing["path_json"] or "{}")
            except Exception:
                old_data = {}
            path_data = self._merge_progress(path_data, old_data)
            path_id = existing["id"]

        db.execute(
            """INSERT INTO learning_paths (id, session_id, path_json) VALUES (?, ?, ?)
               ON DUPLICATE KEY UPDATE path_json = VALUES(path_json), updated_at = NOW()""",
            (path_id, session_id, json.dumps(path_data, ensure_ascii=False))
        )

        await sse_manager.send_event(conn_id, "path_update", {
            "agent": "path_planner", "path_id": path_id, "updated": True,
        })

    @staticmethod
    def _merge_progress(new_data: dict, old_data: dict) -> dict:
        """把旧路径里的学习进度（in_progress / completed）按主题名合并进新路径。"""
        if not isinstance(new_data, dict) or not new_data.get("phases"):
            return new_data
        if not isinstance(old_data, dict) or not old_data.get("phases"):
            return new_data

        old_status: dict[str, str] = {}
        for ph in old_data.get("phases", []):
            for t in ph.get("topics", []):
                st = t.get("status")
                if st in ("in_progress", "completed"):
                    for key in (t.get("title"), t.get("topic_id")):
                        if key:
                            old_status[key] = st
            if ph.get("status") in ("in_progress", "completed"):
                for key in (ph.get("title"), ph.get("topic_id")):
                    if key:
                        old_status[key] = ph["status"]

        if not old_status:
            return new_data

        # completed 优先于 in_progress，避免同一主题被降级
        rank = {"in_progress": 1, "completed": 2}
        for ph in new_data.get("phases", []):
            for t in ph.get("topics", []):
                for key in (t.get("title"), t.get("topic_id")):
                    st = old_status.get(key)
                    if st and rank.get(st, 0) > rank.get(t.get("status"), 0):
                        t["status"] = st
            for key in (ph.get("title"), ph.get("topic_id")):
                st = old_status.get(key)
                if st and rank.get(st, 0) > rank.get(ph.get("status"), 0):
                    ph["status"] = st
        return new_data

    def _load_learning_paths(self) -> dict:
        """加载 trea 学习路径知识库（4条路径，51个知识点）"""
        from config.settings import KNOWLEDGE_DATA_DIR
        path = os.path.join(KNOWLEDGE_DATA_DIR, "learning_paths.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 精简传给 LLM：只保留路径名和知识点列表
                summary = {"paths": []}
                for lp in data.get("learning_paths", []):
                    summary["paths"].append({
                        "path_name": lp["path_name"],
                        "difficulty": lp.get("difficulty", ""),
                        "target_audience": lp.get("target_audience", ""),
                        "nodes": [{"id": n["id"], "name": n["name"],
                                   "chapter": n.get("chapter", ""),
                                   "difficulty": n.get("difficulty", ""),
                                   "estimated_hours": n.get("estimated_hours", 0),
                                   "pre": n.get("pre", [])}
                                  for n in lp.get("nodes", [])],
                    })
                return summary
        except Exception:
            return {"paths": []}

    def _get_profile_summary(self, session_id: str) -> dict:
        # 画像按 user_id 存储，必须由 session 反查 user_id（见 profile_utils）
        return profile_utils.get_profile_summary_by_session(session_id)

    def _get_completed_topics(self, session_id: str) -> list:
        rows = db.fetch_all(
            "SELECT DISTINCT topic FROM learning_records WHERE session_id = ?",
            (session_id,)
        )
        return [r["topic"] for r in rows]

    def _try_parse_path(self, text: str, lps: dict) -> dict:
        import re
        match = re.search(r'\{[\s\S]*"phases"[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        # LLM 失败 → 用 trea 数据生成默认路径
        return learning_paths_to_phases(lps)


def learning_paths_to_phases(data: dict = None) -> dict:
    """将 trea learning_paths.json 转为前端 phases 格式

    输入: {"paths": [...]} 或 {"learning_paths": [...]}
    输出: {"phases": [...], "recommended_next": {...}}
    """
    if data is None:
        from config.settings import KNOWLEDGE_DATA_DIR
        import os as _os
        path = _os.path.join(KNOWLEDGE_DATA_DIR, "learning_paths.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {"phases": [], "recommended_next": {}}

    paths = data.get("learning_paths", data.get("paths", []))
    phases = []
    first_available = None
    for i, lp in enumerate(paths):
        nodes = lp.get("nodes", [])
        total_hours = sum(n.get("estimated_hours", 0) for n in nodes)
        topics = []
        for j, node in enumerate(nodes):
            status = "available" if (i == 0 and j == 0) else "locked"
            if status == "available" and first_available is None:
                first_available = node
            topics.append({
                "topic_id": node["id"],
                "title": node["name"],
                "status": status,
                "estimated_hours": node.get("estimated_hours", 0),
                "difficulty": node.get("difficulty", ""),
                "chapter": node.get("chapter", ""),
                "knowledge_points": node.get("knowledge_points", []),
            })
        phases.append({
            "order": i + 1,
            "title": lp.get("path_name", ""),
            "description": lp.get("description", ""),
            "status": "available" if i == 0 else "locked",
            "progress": 0,
            "topics": topics,
            "estimated_hours": total_hours,
            "difficulty": lp.get("difficulty", ""),
            "target_audience": lp.get("target_audience", ""),
        })

    rec = {}
    if first_available:
        rec = {"topic": first_available["name"], "reason": "从这里开始你的Python学习之旅"}

    return {"phases": phases, "recommended_next": rec}


class TutorAgent(BaseAgent):
    """智能辅导答疑"""

    def __init__(self):
        super().__init__("tutor", "智能辅导答疑专家")

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        profile = self._get_profile_summary(session_id)

        system_template = self._get_system_prompt()
        if not system_template:
            system_template = self._default_system_prompt()

        system_prompt = system_template.replace("{{profile_summary}}", json.dumps(profile, ensure_ascii=False, indent=2))
        system_prompt = system_prompt.replace("{{topic}}", context.get("topic", "未知") if context else "未知")
        topic = context.get("topic", message) if context else message
        retrieved = retriever.retrieve_context(topic, profile)
        system_prompt = system_prompt.replace("{{retrieved_chunks}}",
            retrieved if retrieved else "（暂无相关知识库数据）")

        messages = self._build_messages_with_history(system_prompt, message, context)

        await self._stream_llm(
            conn_id, sse_manager, messages, event_type="content", session_id=session_id
        )

    def _get_profile_summary(self, session_id: str) -> dict:
        # 画像按 user_id 存储，必须由 session 反查 user_id（见 profile_utils）
        return profile_utils.get_profile_summary_by_session(session_id)

    def _default_system_prompt(self) -> str:
        return """你是Python学习辅导专家。解答学生的问题，提供文字解释 + 代码示例 + 图解说明。
语言通俗易懂，匹配学生水平。鼓励学生独立思考，不直接给完整答案。"""


path_planner_agent = PathPlannerAgent()
tutor_agent = TutorAgent()
