"""题目生成智能体 — 生成分层练习题（讯飞星火驱动）"""

import json
import uuid
from app.agents.base import BaseAgent
from app.core import profile_utils, vocab
from app.core.sse_manager import sse_manager
from app.db.sqlite_client import db
from app.rag.retriever import retriever

# 输出格式说明（替代 quiz_templates.json 的原始结构——原文件里的
# "单选题：从4个选项中选择1个正确答案" 等示例文字会被 LLM 误抄成题干）
# ⚠️ 只保留「可自动判分」的客观题类型：编程题 / 开放题前端无法判分，
#    若混进题目里会被算进总分（5 题夹 2 道 → 全对也只有 60%），故不提供示例。
QUIZ_FORMAT_SPEC = """{
  "title": "练习题标题",
  "questions": [
    {"id": "q1", "type": "single_choice", "level": "basic", "stem": "完整具体的题干正文",
     "options": ["A. 选项内容", "B. 选项内容", "C. 选项内容", "D. 选项内容"],
     "answer": "A", "explanation": "解析"},
    {"id": "q2", "type": "multi_choice", "level": "intermediate", "stem": "完整题干",
     "options": ["A. 内容", "B. 内容", "C. 内容", "D. 内容"], "answers": ["A", "C"], "explanation": "解析"},
    {"id": "q3", "type": "true_false", "level": "basic", "stem": "一个可判断正误的陈述句",
     "options": ["A. 正确", "B. 错误"], "answer": "A", "explanation": "解析"}
  ]
}
⚠️ 以上仅是字段格式说明：所有示例值（"完整题干正文"、"选项内容" 等）都必须替换成真实、具体、可作答的题目内容。
⚠️ 禁止出编程题、开放题、填空题、简答题。type 字段只允许这三个英文值之一：single_choice / multi_choice / true_false。禁止使用其它任何类型名或中文类型名。"""

# 清洗话题后如果只剩这些词，说明用户没给知识点（"我要三道题" → "题"），用兜底主题
_GENERIC_TOPICS = {
    "题", "题目", "练习", "习题", "测试", "考题", "例题", "代码", "学习",
    "基础", "python", "Python", "python基础", "Python基础", "综合", "综合练习",
}


class QuizGenAgent(BaseAgent):
    """练习题生成"""

    def __init__(self):
        super().__init__("quiz_gen", "练习题生成专家")

    async def process(self, conn_id: str, session_id: str, message: str, context: dict = None):
        # 清洗查询词：去掉"给我出几道""练习题"等噪声，提取纯知识点关键词
        raw = message.strip()
        topic = self._clean_topic(raw)
        # 从消息中提取用户想要的题数（"三道"→3），默认 5
        count = self._extract_count(raw) or 5
        profile = self._get_profile_summary(session_id)

        # 根据画像确定题目难度分布，并按用户要的题数缩放
        level = vocab.normalize_level(profile.get("knowledge_base", {}).get("level"))
        dist = self._scale_dist(vocab.level_to_quiz_dist(level), count)

        # 加载系统提示与题目模板
        system_template = self._get_system_prompt()
        if not system_template:
            system_template = self._default_system_prompt()

        system_prompt = system_template.replace("{{knowledge_level}}", level)
        system_prompt = system_prompt.replace("{{cognitive_level}}", self._bloom_str(profile))
        system_prompt = system_prompt.replace("{{error_patterns}}", json.dumps(profile.get("error_patterns", {}), ensure_ascii=False))
        system_prompt = system_prompt.replace("{{topic}}", topic)
        system_prompt = system_prompt.replace("{{template_specs}}", QUIZ_FORMAT_SPEC)
        system_prompt = system_prompt.replace("{{count}}", str(count))
        system_prompt = system_prompt.replace("{{quiz_distribution}}", dist["desc"])
        system_prompt += ("\n\n⚠️ 每道题的 stem 必须是完整、具体的题目正文（含明确的考点），"
                          "绝对不能出现「单选题：从4个选项中选择1个正确答案」这类模板说明文字。")

        # 从习题库检索匹配题目（只查习题，不混教材PPT）
        retrieved = retriever.retrieve_exercises_context(topic, top_k=15)
        if retrieved:
            system_prompt += (
                f"\n\n📚 知识库匹配习题（学生级别: {level}，题目分布: {dist['desc']}）：\n"
                + retrieved
                + "\n\n⚠️ 请直接使用上述题库中的习题！不必自己编题。"
                  "每道题输出时标注来源为题库ID（如「来源: 题库E001」）。"
                  "如果题库中某难度层级的题目不够，再自行补充并标注「来源: 自编」。"
            )
        else:
            system_prompt += (
                "\n\n（知识库中未找到匹配习题，请自行生成。标注「来源: 自编」。）"
            )

        quiz_id = f"res_quiz_{uuid.uuid4().hex[:8]}"

        # 先告知前端即将生成题目
        await sse_manager.send_event(conn_id, "thinking", {
            "agent": "quiz_gen",
            "status": f"正在为「{topic}」生成{count}道练习题..."
        })

        messages = self._build_messages_with_history(
            system_prompt,
            f"请为「{topic}」生成{count}道分层练习题，难度分布: {dist['desc']}。"
            "⚠️ 每题 explanation 控制在 40 字以内，选项简短，只输出一个 JSON 对象。输出标准JSON格式。",
            context
        )

        # ⚠️ 不走流式：静默收集完整响应，避免原始 JSON 显示在聊天中
        from app.core.llm_client import spark_llm
        full_content = ""
        async for chunk in spark_llm.chat_stream(messages, max_tokens=2560):
            if chunk.get("error"):
                await sse_manager.send_event(conn_id, "content", {
                    "agent": "quiz_gen", "type": "error",
                    "chunk": f"\n\n[错误] {chunk['error']}"
                })
                break
            full_content += chunk.get("content", "")

        # 保存 AI 回复到对话历史
        if full_content:
            db.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, "assistant", f"[生成练习题: {topic}]")
            )

        # 解析 LLM JSON 并转为前端 QuizCard 期望的扁平格式
        parsed = self._normalize_quiz(self._try_parse_quiz(full_content), topic, dist, count)

        # 解析失败兜底：用更强约束重试一次，仍失败再用默认题目
        if not parsed.get("questions"):
            print(f"[quiz_gen] LLM 输出解析失败，重试一次。原始输出(前300字): {full_content[:300]}")
            retry_messages = [
                {"role": "system", "content": system_prompt
                 + "\n\n⚠️ 上一次输出无法解析。这次只输出一个JSON对象，以 { 开头、以 } 结尾，"
                   "不要任何解释文字，不要 markdown 代码块以外的内容。"
                   "格式：{\"title\":\"...\",\"questions\":[{\"id\":\"q1\",\"type\":\"single_choice\","
                   "\"stem\":\"...\",\"options\":[\"A. ...\",\"B. ...\"],\"answer\":\"A\"}]}"},
                {"role": "user", "content": f"请为「{topic}」生成{count}道练习题，只输出JSON。"},
            ]
            retry_content = ""
            async for chunk in spark_llm.chat_stream(retry_messages, max_tokens=4096):
                if chunk.get("error"):
                    break
                retry_content += chunk.get("content", "")
            if retry_content:
                parsed = self._normalize_quiz(self._try_parse_quiz(retry_content), topic, dist, count)

        if not parsed.get("questions"):
            print(f"[quiz_gen] 重试仍失败，使用默认题目。")
            parsed = self._fallback_quiz(topic, dist)

        # resource_start 已提前发送，这里直接发送解析后的 JSON 作为内容，前端 QuizCard 直接渲染
        await sse_manager.send_event(conn_id, "content", {
            "agent": "quiz_gen", "type": "text",
            "chunk": json.dumps(parsed, ensure_ascii=False)
        })

        db.execute(
            """INSERT INTO resources (id, session_id, type, title, topic, content, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (quiz_id, session_id, "quiz", f"{topic}分层练习题", topic,
             json.dumps(parsed, ensure_ascii=False),
             json.dumps({"difficulty": "分层", "question_count": len(parsed.get("questions", []))}, ensure_ascii=False))
        )

        await sse_manager.send_event(conn_id, "resource_done", {
            "agent": "quiz_gen", "resource_id": quiz_id, "type": "quiz", "status": "completed",
        })

    @staticmethod
    def _clean_topic(message: str) -> str:
        """从用户消息中提取干净的知识点关键词，用于知识库检索"""
        import re
        result = message.strip()
        # 去掉数量短语：三道 / 3道 / 几道 / 一套 / 五个 / 10题 等
        result = re.sub(r"[0-9一二两三四五六七八九十]+\s*(道|题|个|套)", "", result)
        # 去掉常见的噪声词
        noise = ["给我出几道", "给我出", "出几道", "练习题", "题目", "出一道",
                 "来几道", "做一些", "做几道", "出题", "做题", "测验", "的题",
                 "我想", "我要", "我想要", "帮我", "请", "一下", "一些", "几个",
                 "关于", "来一套", "出一套", "给我来", "练习", "考题", "测试",
                 "的题目"]
        for n in sorted(set(noise), key=len, reverse=True):  # 长的先去掉
            result = result.replace(n, "")
        # 去掉首尾残留的标点/助词/动词（"出""来"等开头动词）
        result = re.sub(r"^[出来给做]+\s*", "", result)
        result = re.sub(r"^[的了吗呢吧啊，,。\s]+|[的了吗呢吧啊，,。\s]+$", "", result)
        result = result.strip()
        # 清洗后只剩"题""练习"这类无信息量的词（或空）→ 用兜底主题，
        # 否则资源标题会变成"题 分层练习题"，还会被 LLM 原样写进题干
        if len(result) < 2 or result in _GENERIC_TOPICS:
            return "综合练习"
        return result

    @staticmethod
    def _extract_count(message: str) -> int | None:
        """从消息中提取用户想要的题数（"三道"→3，"10道"→10），提取不到返回 None"""
        import re
        m = re.search(r"([0-9]+|[一二两三四五六七八九十]+)\s*道", message)
        if not m:
            return None
        num = m.group(1)
        cn = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        try:
            n = int(num) if num.isdigit() else cn.get(num)
        except ValueError:
            n = None
        if not n:
            return None
        return min(20, max(1, n))

    @staticmethod
    def _scale_dist(dist: dict, count: int) -> dict:
        """把画像默认的难度分布按用户要的题数等比缩放（至少1道基础题）"""
        base, mid, adv = dist["base"], dist["mid"], dist["adv"]
        total = (base + mid + adv) or 1
        nb = max(1 if base else 0, round(count * base / total))
        nm = round(count * mid / total)
        na = count - nb - nm
        while na < 0:  # 超了就从多到少退
            if nb > 1:
                nb -= 1
            elif nm > 0:
                nm -= 1
            else:
                na += 1
        desc = f"{nb}基础+{nm}进阶+{na}挑战" if (nm or na) else f"{nb}基础"
        return {"desc": desc, "base": nb, "mid": nm, "adv": max(na, 0)}

    @staticmethod
    def _fallback_quiz(topic: str, dist: dict = None) -> dict:
        """LLM 解析失败时的默认题目兜底"""
        dist = dist or {"base": 3, "mid": 0, "adv": 0}
        return {
            "title": f"{topic} 练习题",
            "questions": [
                {"id": "q1", "type": "single_choice", "stem": f"下列关于{topic}的描述，正确的是？",
                 "options": ["A. 选项一", "B. 选项二", "C. 选项三", "D. 选项四"], "answer": "A"},
                {"id": "q2", "type": "single_choice", "stem": f"{topic}在编程中的主要作用是？",
                 "options": ["A. 提高代码可读性", "B. 降低运行速度", "C. 增加内存占用", "D. 以上都不对"], "answer": "A"},
                {"id": "q3", "type": "true_false", "stem": f"{topic}是Python编程中的重要概念。",
                 "options": ["A. 正确", "B. 错误"], "answer": "A"},
            ],
            "levels": {"basic": {"count": dist["base"]}, "intermediate": {"count": dist["mid"]}, "advanced": {"count": dist["adv"]}},
        }

    @staticmethod
    def _quiz_distribution(level: str) -> dict:
        """根据学生画像级别确定题目难度分布（统一由 app.core.vocab 提供）

        Returns:
            {"desc": "3基础+1进阶+1挑战", "base": 3, "mid": 1, "adv": 1}
        """
        return vocab.level_to_quiz_dist(level)

    @staticmethod
    def _normalize_quiz(raw: dict, title: str, dist: dict, max_questions: int = 5) -> dict:
        """将 LLM 输出的任意嵌套 JSON 转为前端 QuizCard 期望的扁平格式"""
        questions = []

        # 如果 LLM 输出扁平 questions 数组且有内容，直接用
        if "questions" in raw and isinstance(raw["questions"], list) and len(raw["questions"]) > 0:
            questions = raw["questions"]
        else:
            # questions 为空或不存在 → 尝试从嵌套结构提取
            # 尝试从嵌套结构中提取
            def _ensure_id(q, i):
                if isinstance(q, dict) and not q.get("id"):
                    q["id"] = f"q{i + 1}"
                return q

            def _extract(obj: dict, default_type: str, stem_keys: tuple):
                """从嵌套对象中提取题目，stem_keys 是备选的 stem 来源字段"""
                for q in obj:
                    if isinstance(q, dict):
                        q.setdefault("type", default_type)
                        # 尝试多个字段填充 stem
                        if not q.get("stem"):
                            for key in stem_keys:
                                if q.get(key):
                                    q["stem"] = q.pop(key)
                                    break
                        # 最后回退：用 description 或 question
                        if not q.get("stem"):
                            q["stem"] = q.get("description", q.get("question", ""))
                        _ensure_id(q, len(questions))
                        questions.append(q)

            # 选择题
            choice = raw.get("choice", {})
            for key, qtype in [("single_choice", "single_choice"),
                               ("multi_choice", "multi_choice"),
                               ("true_false", "true_false")]:
                arr = choice.get(key, [])
                _extract(arr if isinstance(arr, list) else [arr], qtype, ("stem",))

            # 编程题（只在有内容时提取）
            code = raw.get("code", {})
            if isinstance(code, dict):
                code_arr = [code.get("structure", code)]
            else:
                code_arr = code if isinstance(code, list) else []
            code_arr = [c for c in code_arr if isinstance(c, dict) and (c.get("stem") or c.get("description"))]
            _extract(code_arr, "code", ("description", "stem", "title"))

            # 开放题（只在有内容时提取）
            open_d = raw.get("open", {})
            if isinstance(open_d, dict):
                open_arr = [open_d.get("structure", open_d)]
            else:
                open_arr = open_d if isinstance(open_d, list) else []
            for o in open_arr:
                if isinstance(o, dict) and (o.get("stem") or o.get("scenario") or o.get("description") or o.get("tasks")):
                    o.setdefault("type", "open")
                    if not o.get("stem"):
                        parts = [o.get("scenario", o.get("description", ""))]
                        for t in o.get("tasks", []):
                            parts.append(f"• {t}")
                        o["stem"] = "\n".join(filter(None, parts))
                    _ensure_id(o, len(questions))
                    questions.append(o)

        result = {
            "title": f"{title} 分层练习题",
            "questions": questions[:max_questions],
            "levels": {
                "basic": {"count": dist["base"]},
                "intermediate": {"count": dist["mid"]},
                "advanced": {"count": dist["adv"]},
            },
        }
        # 选项统一转为前端 QuizCard 期望的 {key, text} 对象格式；
        # 同时把 LLM 偷偷输出的非法题型（如"填空题"）归一化为前端支持的类型
        SUPPORTED_TYPES = {"single_choice", "multi_choice", "true_false", "code", "open"}
        for q in result["questions"]:
            q["options"] = QuizGenAgent._normalize_options(q.get("options"))
            t = str(q.get("type", "")).strip().lower()
            if t not in SUPPORTED_TYPES:
                opts = q.get("options") or []
                if len(opts) == 2:
                    q["type"] = "true_false"
                elif len(opts) > 2:
                    q["type"] = "single_choice"
                else:
                    q["type"] = "open"
        return result

    @staticmethod
    def _normalize_options(options) -> list:
        """把各种形态的选项统一为 [{key:'A', text:'...'}, ...]

        兼容三种输入：
        - 已是 {"key":"A","text":"..."} 对象 → 原样保留
        - "A. 正确" / "A、正确" / "A:正确" 字符串 → 拆分字母前缀
        - 无前缀纯文本 "正确" → 按顺序分配 A/B/C/D
        """
        import re
        if not isinstance(options, list):
            return options
        normalized = []
        for i, opt in enumerate(options):
            if isinstance(opt, dict) and opt.get("text") is not None:
                normalized.append({"key": str(opt.get("key", chr(65 + i))), "text": str(opt["text"])})
            elif isinstance(opt, str):
                m = re.match(r"^\s*([A-Za-z])\s*[.、:：)]\s*(.+)$", opt)
                if m:
                    normalized.append({"key": m.group(1).upper(), "text": m.group(2).strip()})
                else:
                    normalized.append({"key": chr(65 + i), "text": opt.strip()})
            elif isinstance(opt, (int, float, bool)):
                normalized.append({"key": chr(65 + i), "text": str(opt)})
        return normalized

    def generate_sync(self, session_id: str, topic: str, question_count: int = 5) -> dict:
        """同步生成练习题（不走 SSE，供 REST API 调用）

        Returns:
            QuizCard 兼容的 dict: {"title":"...", "questions":[...], "levels":{...}}
        """
        profile = self._get_profile_summary(session_id)
        level = vocab.normalize_level(profile.get("knowledge_base", {}).get("level"))
        dist = vocab.level_to_quiz_dist(level)

        system_template = self._get_system_prompt()
        if not system_template:
            system_template = self._default_system_prompt()

        system_prompt = system_template.replace("{{knowledge_level}}", level)
        system_prompt = system_prompt.replace("{{cognitive_level}}", self._bloom_str(profile))
        system_prompt = system_prompt.replace("{{error_patterns}}", json.dumps(profile.get("error_patterns", {}), ensure_ascii=False))
        system_prompt = system_prompt.replace("{{topic}}", topic)
        system_prompt = system_prompt.replace("{{template_specs}}", QUIZ_FORMAT_SPEC)
        system_prompt = system_prompt.replace("{{count}}", str(question_count))
        system_prompt = system_prompt.replace("{{quiz_distribution}}", dist["desc"])

        # 从习题库检索
        retrieved = retriever.retrieve_exercises_context(topic, top_k=15)
        if retrieved:
            system_prompt += (
                f"\n\n📚 知识库匹配习题（学生级别: {level}，题目分布: {dist['desc']}）：\n"
                + retrieved
                + "\n\n⚠️ 请直接使用上述题库中的习题！不必自己编题。"
                  "每道题输出时标注来源为题库ID（如「来源: 题库E001」）。"
                  "如果题库中某难度层级的题目不够，再自行补充并标注「来源: 自编」。"
            )
        else:
            system_prompt += "\n\n（知识库中未找到匹配习题，请自行生成。标注「来源: 自编」。）"

        # ⚡ 提速关键：生成耗时几乎与输出字数成正比（实测 5题长解析 39.6s → 精简后 4.7s）
        # 所以这里明确限制解析长度、禁止多余输出，并把 max_tokens 从 4096 降到 2048
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"请为「{topic}」生成{question_count}道分层练习题，难度分布: {dist['desc']}。"
                "⚠️ 只出选择题（单选+多选）和判断题，不要出编程题和开放题。"
                "⚠️ 每题 explanation 控制在 25 字以内，选项文字简短。"
                "⚠️ 只输出一个 JSON 对象，不要任何解释性文字、不要 markdown 代码块。输出标准JSON格式。"
            )},
        ]

        import traceback as _tb
        import uuid as _uuid

        # 调用 LLM 生成
        try:
            from app.core.llm_client import spark_llm
            raw_text = spark_llm.chat_sync(messages, max_tokens=3072)
        except Exception as e:
            print(f"[quiz_gen] LLM调用失败: {e}")
            _tb.print_exc()
            raise RuntimeError(f"AI服务调用失败: {str(e)[:100]}") from e

        # 解析 LLM 输出
        try:
            raw = self._try_parse_quiz(raw_text)
            parsed = self._normalize_quiz(raw, topic, dist)
        except Exception as e:
            print(f"[quiz_gen] 题目解析失败: {e}")
            print(f"[quiz_gen] LLM原始输出(前500字): {raw_text[:500]}")
            _tb.print_exc()
            parsed = {"questions": []}

        # 解析失败/被截断 → 用更严格的提示重试一次（少出题、解析更短，保证 JSON 完整）
        if not parsed.get("questions"):
            print(f"[quiz_gen] 首次生成未拿到有效题目，重试一次（精简输出）")
            retry_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"请为「{topic}」生成3道选择题（单选/多选/判断皆可）。"
                    "⚠️ 每题 explanation 不超过 15 字，选项不超过 12 字。"
                    "⚠️ 只输出一个 JSON 对象，必须完整结束（以 } 结尾），不要任何其它文字。"
                )},
            ]
            try:
                retry_text = spark_llm.chat_sync(retry_messages, max_tokens=2048)
                parsed = self._normalize_quiz(self._try_parse_quiz(retry_text), topic, dist)
            except Exception as e:
                print(f"[quiz_gen] 重试调用失败: {e}")

        if not parsed.get("questions"):
            print(f"[quiz_gen] 重试仍无有效题目，原始输出(前500字): {raw_text[:500]}")
            raise RuntimeError("AI未能生成有效题目，请重试")

        # 保存到 resources 表（不阻塞主流程）
        quiz_id = f"res_quiz_{_uuid.uuid4().hex[:8]}"
        try:
            db.execute(
                """INSERT INTO resources (id, session_id, type, title, topic, content, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (quiz_id, session_id, "quiz", f"{topic}分层练习题", topic,
                 json.dumps(parsed, ensure_ascii=False),
                 json.dumps({"difficulty": "分层", "question_count": len(parsed.get("questions", []))}, ensure_ascii=False))
            )
        except Exception as e:
            print(f"[quiz_gen] 保存练习失败（不影响使用）: {e}")

        parsed["resource_id"] = quiz_id
        return parsed

    def _get_profile_summary(self, session_id: str) -> dict:
        # 画像按 user_id 存储，必须由 session 反查 user_id，
        # 否则在别的会话写入的画像读不到 → 难度分级失效。
        return profile_utils.get_profile_summary_by_session(session_id)

    def _bloom_str(self, profile: dict) -> str:
        cl = profile.get("cognitive_level", {})
        if not isinstance(cl, dict):
            return "默认入门"
        # 画像里 cognitive_level 的键是中文（记忆/理解/应用/分析/评价/创造）或历史英文值，
        # 排除 thinking_style 这类非数值字段后，只要有一项 > 0 就展示
        vals = {}
        for k, v in cl.items():
            try:
                if float(v) > 0:
                    vals[k] = v
            except (TypeError, ValueError):
                continue
        if vals:
            return ", ".join(f"{k}={v}" for k, v in vals.items())
        return "默认入门"

    def _load_quiz_templates(self) -> dict:
        import os, yaml
        from config.settings import COURSE_CONFIG_PATH, ACTIVE_COURSE
        path = os.path.join(COURSE_CONFIG_PATH, ACTIVE_COURSE, "quiz_templates.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _try_parse_quiz(self, text: str) -> dict:
        """从LLM输出中提取JSON，支持裸JSON和```json代码块包裹

        额外容错：输出被 max_tokens 截断时（JSON 不完整），逐个抢救
        已完整输出的题目对象，避免整套题目白白作废。
        """
        import re

        content = text.strip()

        # 策略1: 去掉 ```json ... ``` 代码块包裹
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if m:
            content = m.group(1).strip()

        # 策略2: 括号计数找最外层 {"..."questions"...} 对象
        try:
            return self._brace_parse_json(content)
        except ValueError:
            pass

        # 策略3: 正则兜底（非贪婪）
        match = re.search(r'\{[\s\S]*?"questions"[\s\S]*?\}', content)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # 策略4: JSON 被截断 → 抢救所有已完整的题目对象
        salvaged = self._salvage_questions(content)
        if salvaged:
            print(f"[quiz_gen] JSON 被截断，已抢救出 {len(salvaged)} 道完整题目")
            return {"questions": salvaged}

        return {"raw": text, "questions": []}

    @staticmethod
    def _salvage_questions(text: str) -> list:
        """从被截断的 JSON 文本中抢救出所有完整的题目对象（含 stem 的 {...}）"""
        questions = []
        i = 0
        n = len(text)
        while i < n:
            if text[i] != '{':
                i += 1
                continue
            depth, in_str, esc = 0, False, False
            end = -1
            for j in range(i, n):
                ch = text[j]
                if esc:
                    esc = False
                    continue
                if ch == '\\':
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            if end == -1:  # 从这里开始就不完整了，后面也不可能完整
                break
            try:
                obj = json.loads(text[i:end + 1])
            except json.JSONDecodeError:
                i += 1
                continue
            if isinstance(obj, dict) and obj.get("stem") and "questions" not in obj:
                questions.append(obj)
            i = end + 1
        # 去重（按 stem）
        seen, uniq = set(), []
        for q in questions:
            if q["stem"] not in seen:
                seen.add(q["stem"])
                uniq.append(q)
        return uniq

    @staticmethod
    def _brace_parse_json(text: str) -> dict:
        """括号计数找第一个完整JSON对象（含 "questions" 键）"""
        start = text.find('{')
        if start == -1:
            raise ValueError("no brace")

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    parsed = json.loads(candidate)
                    # 接受 questions / choice / code / open 任意格式
                    if any(k in parsed for k in ("questions", "choice", "code", "open")):
                        return parsed
        raise ValueError("no matching close brace")

    def _default_system_prompt(self) -> str:
        return """你是Python练习题专家。基于学生画像生成分层练习题。
- 基础层: 巩固概念，单选题 + 判断题
- 进阶层: 稍复杂的单选/多选与代码输出判断
- 挑战层: 综合应用型选择题
⚠️ 只出客观题（单选/多选/判断），禁止出编程题、开放题、填空题——这些前端无法自动判分。
⚠️ 优先使用知识库中的习题，标注来源。知识库不足时再自行补充。
输出标准JSON格式：{"title":"...","questions":[{...}]}"""


quiz_gen_agent = QuizGenAgent()
