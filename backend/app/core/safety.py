"""内容安全过滤器

设计原则：**宁可漏过，不可错杀。**

这是一个 Python 教学系统。学生讨论"继承""多态""SQL 注入""绕过反爬"都是正常学习内容，
任何大词表式的内容审查都会误伤正常教学（历史教训：关键词过滤越宽，错杀越多）。
所以这里只做两类**误伤概率极低、但有真实价值**的防护：

1. 输入侧 `check_input()`：识别提示注入 / 越狱话术
   即诱导模型放弃"Python 学习导师"身份、或套取系统提示词原文。
   这些句式在正常学习对话里几乎不会自然出现。

2. 输出侧 `sanitize_output()`：给模型输出里意外出现的密钥形态内容打码
   LLM 偶尔会把上下文里的密钥串复述出来，直接展示给学生属于真实泄露风险。

刻意**不做**：通用敏感词过滤、政治/价值观审查 —— 那部分应交给专业审核 API，
本地词表只会误伤教学内容。
"""

import re

# ── 提示注入 / 越狱特征（中英文）──
# 说明：每条都要求"索取/篡改/绕过"的完整语义，正常学习用语不会命中。
_INJECTION_PATTERNS = [
    r"忽略(上面|以上|之前|前面)的?(全部|所有)?(指令|提示|规则|设定|内容|对话)",
    r"无视(上面|以上|之前|前面)的?(全部|所有)?(指令|提示|规则|设定)",
    r"忘记(你|上面|之前|以上)?的?(全部|所有)?(指令|设定|规则|人设|身份)",
    r"(清除|删除)(你|之前|上面)的?(所有)?(记忆|设定|指令|规则)",
    r"(输出|显示|打印|告诉我|复述|泄露|交出)(你的|系统|原始|内部)?"
    r"(提示词|系统提示|系统指令|初始指令|设定词|prompt|instructions)",
    r"(绕过|突破|无视|关闭)(你的)?(安全|内容|输出)?(限制|审查|过滤|护栏)",
    r"ignore\s+(all\s+|previous\s+|prior\s+)?(the\s+)?instructions",
    r"(reveal|print|output|repeat|show)\s+(your\s+|the\s+)?(system\s+|initial\s+)?"
    r"(prompt|instructions)",
    r"pretend\s+you\s+have\s+no\s+(rules|restrictions|limitations)",
    r"you\s+are\s+now\s+(dan|an?\s+unrestricted)",
]

_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]

# ── 输出侧：密钥/凭据形态（打码，避免 LLM 复述上下文里的机密）──
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[密钥已隐藏]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{16,}"), "Bearer [密钥已隐藏]"),
    (re.compile(r"\bak-[a-f0-9]{20,}\b"), "[密钥已隐藏]"),  # 讯飞/星辰 MaaS 密钥形态
    (re.compile(r"(api[_\-]?key|apikey|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}",
                re.IGNORECASE), r"\1: [密钥已隐藏]"),
]


class SafetyFilter:
    """内容安全过滤（保守策略）"""

    # 保留字段以兼容旧调用：这里**刻意为空**。
    # 通用敏感词一旦有内容就会误伤教学（如"注入""爬虫绕过"），请勿在此添加词表。
    SENSITIVE_WORDS = set()

    @staticmethod
    def check_input(text: str) -> tuple[bool, str]:
        """检查用户输入是否为提示注入/越狱话术。

        返回 (是否放行, 原因)。放行=True。
        """
        if not text or len(text.strip()) < 4:
            return True, ""
        msg = text.strip()
        for pattern in _INJECTION_RE:
            if pattern.search(msg):
                return False, "疑似诱导模型越权的提示词注入"
        return True, ""

    @staticmethod
    def sanitize_output(text: str) -> str:
        """对模型输出做脱敏处理，隐藏可能被复述出来的密钥。"""
        if not text:
            return text
        result = text
        for pattern, repl in _SECRET_PATTERNS:
            result = pattern.sub(repl, result)
        return result

    @staticmethod
    def check_sensitive(text: str) -> tuple[bool, str]:
        """兼容旧接口：通用敏感词检查。当前未启用大词表（见 SENSITIVE_WORDS 说明）。"""
        for word in SafetyFilter.SENSITIVE_WORDS:
            if word in text:
                return False, f"包含敏感内容: {word}"
        return True, ""

    @staticmethod
    def filter_text(text: str) -> str:
        """兼容旧接口：同义于 sanitize_output。"""
        result = text
        for word in SafetyFilter.SENSITIVE_WORDS:
            result = result.replace(word, "***")
        return SafetyFilter.sanitize_output(result)

    @staticmethod
    def verify_facts(content: str, references: list[str]) -> tuple[bool, str]:
        """事实性校验。无知识库引用时跳过；有引用时只做产出有效性检查。"""
        if not references:
            return True, "无知识库引用，跳过事实校验"
        # 有引用却产出为空/过短 = 生成异常，提示重试
        if content is not None and len(content.strip()) < 20:
            return False, "生成内容过短，可能未正确使用知识库"
        return True, ""


safety_filter = SafetyFilter()
