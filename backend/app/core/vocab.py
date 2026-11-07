"""统一词表 —— 画像标签 ↔ 难度 / 兴趣方向的唯一映射出口。

背景（历史 bug）：同一个「编程基础」在项目里出现了三套键，
  · 入门问卷（profile.py QUESTION_MAP）写入中文标签：零基础 / 了解一点 / 有基础 / 比较熟练
  · 路径规划（learning_path.py）用：零基础 / 了解一点 / 有一点基础 / 有基础 / 比较熟练
  · 出题难度（quiz_gen.py）与检索过滤（retriever.py）却用：零基础 / 入门 / 进阶 / 熟练
结果：问卷用户永远命不中后两套键，全部落到默认档（难度分布 3基础+1进阶+1挑战、
检索一律按「简单」过滤，把中等/进阶教材全滤掉）。

「兴趣方向」问题更严重：问卷写入的是中文标签（数据分析/AI、Web开发…），
而 INTEREST_TO_PATHS 的键是英文（data_ai/web/game…），永远匹配不上，
所有人的方向路径都退化成默认的 path_2（网络安全/网络编程）。

约定：所有需要「画像标签 → 内部 key / 难度」的地方，一律 import 本模块，
不要再各自维护映射表。规范标签以「入门问卷写入的中文标签」为准。
"""

import re

# ================================================================
# 编程基础（profiles: knowledge_base.level）
# ================================================================

# 各种历史/来源标签 → 规范标签
LEVEL_ALIASES = {
    # 规范值（问卷写入）
    "零基础": "零基础",
    "了解一点": "了解一点",
    "有基础": "有基础",
    "比较熟练": "比较熟练",
    # 对话式画像（profiler 提取提示词用的是这套）
    "入门": "了解一点",
    "进阶": "有基础",
    "熟练": "比较熟练",
    # 早期路径策略里的历史键
    "有一点基础": "了解一点",
}

DEFAULT_LEVEL = "零基础"


def normalize_level(level) -> str:
    """把任意来源的「编程基础」标签归一化为规范标签；无法识别时返回默认档。"""
    if level is None:
        return DEFAULT_LEVEL
    s = str(level).strip().strip("[]'\" ")
    return LEVEL_ALIASES.get(s, DEFAULT_LEVEL)


# 规范标签 → 知识库难度（exercises.json / learning_paths.json 的 difficulty 取值：
# 简单 / 中等 / 进阶）
LEVEL_TO_DIFFICULTY = {
    "零基础": "简单",
    "了解一点": "简单",
    "有基础": "中等",
    "比较熟练": "进阶",
}


def level_to_difficulty(level) -> str:
    return LEVEL_TO_DIFFICULTY.get(normalize_level(level), "简单")


# 规范标签 → 出题难度分布（基础 / 进阶 / 挑战）
LEVEL_TO_QUIZ_DIST = {
    "零基础": {"desc": "4基础+1进阶", "base": 4, "mid": 1, "adv": 0},
    "了解一点": {"desc": "3基础+1进阶+1挑战", "base": 3, "mid": 1, "adv": 1},
    "有基础": {"desc": "1基础+2进阶+2挑战", "base": 1, "mid": 2, "adv": 2},
    "比较熟练": {"desc": "2进阶+3挑战", "base": 0, "mid": 2, "adv": 3},
}


def level_to_quiz_dist(level) -> dict:
    return dict(LEVEL_TO_QUIZ_DIST.get(normalize_level(level), LEVEL_TO_QUIZ_DIST["了解一点"]))


# 规范标签 → 路径起点策略（解锁多少个基础主题）
LEVEL_TO_STRATEGY = {
    "零基础": {"mode": "full", "desc": "从零开始", "unlock_count": 1},
    "了解一点": {"mode": "fast", "desc": "快速过基础", "unlock_count": 4},
    "有基础": {"mode": "fast", "desc": "快速过基础", "unlock_count": 6},
    "比较熟练": {"mode": "skip", "desc": "直接进入方向", "unlock_count": 99},
}


def level_to_strategy(level) -> dict:
    return dict(LEVEL_TO_STRATEGY.get(normalize_level(level), LEVEL_TO_STRATEGY[DEFAULT_LEVEL]))


# ================================================================
# 兴趣方向（profiles: interest_tendency.directions）
# ================================================================

# 中文标签 / 历史英文 key / 常见别名 → 内部方向 key
INTEREST_ALIASES = {
    "数据分析/AI": "data_ai",
    "数据分析": "data_ai",
    "data_ai": "data_ai",
    "ai": "data_ai",
    "人工智能": "data_ai",
    "机器学习": "data_ai",
    "web": "web",
    "Web开发": "web",
    "web开发": "web",
    "爬虫": "web",
    "网络编程": "web",
    "网络安全": "web",
    "游戏开发": "game",
    "游戏": "game",
    "game": "game",
    "自动化脚本": "automation",
    "自动化": "automation",
    "automation": "automation",
    "算法": "algorithm",
    "algorithm": "algorithm",
}

# 内部方向 key → trea 路径 id（path_1 是公共基础，不在此表）
INTEREST_TO_PATHS = {
    "data_ai": ["path_3", "path_4"],   # 数据分析 → AI
    "web": ["path_2"],                 # Web开发 → 爬虫/网络编程
    "game": ["path_4"],                # 游戏 → AI/ML
    "automation": ["path_2"],          # 自动化 → 网络编程
    "algorithm": ["path_4"],           # 算法 → AI/ML
}

DEFAULT_INTEREST_PATHS = ["path_2"]


def normalize_interest(interest) -> str | None:
    """把画像里的兴趣方向归一化为内部 key；无法识别时返回 None。

    兼容三种写法：
      · 问卷标签 "数据分析/AI"
      · 历史英文 key "data_ai"
      · 多值/JSON 数组 '["数据分析/AI", "Web开发"]'
    """
    if not interest:
        return None
    s = str(interest).strip().strip("[]'\" ")
    if not s:
        return None
    if s in INTEREST_ALIASES:
        return INTEREST_ALIASES[s]
    # 多值：逗号 / 中文逗号 / 斜杠 / 顿号 / 分号 / 竖线
    for token in re.split(r"[,\uff0c/\u3001;；|]+", s):
        t = token.strip().strip("[]'\" ")
        if not t:
            continue
        if t in INTEREST_ALIASES:
            return INTEREST_ALIASES[t]
        if t.lower() in INTEREST_ALIASES:
            return INTEREST_ALIASES[t.lower()]
    return None


def interest_to_paths(interest) -> list[str]:
    """规范化兴趣方向并返回对应的 trea 路径 id 列表；无法识别返回默认方向。"""
    key = normalize_interest(interest)
    if not key:
        return list(DEFAULT_INTEREST_PATHS)
    return list(INTEREST_TO_PATHS.get(key, DEFAULT_INTEREST_PATHS))
