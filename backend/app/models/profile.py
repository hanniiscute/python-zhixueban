"""Pydantic 数据模型 — 学生画像"""

from pydantic import BaseModel, Field


# ======== 维度1：知识基础 ========
class KnowledgeBase(BaseModel):
    level: str = "未知"  # 零基础 | 入门 | 进阶 | 熟练
    known_concepts: list[str] = Field(default_factory=list)
    unknown_concepts: list[str] = Field(default_factory=list)
    score_map: dict[str, int] = Field(default_factory=dict)


# ======== 维度2：学习风格 ========
class LearningStyle(BaseModel):
    type: str = "未知"  # visual | verbal | active | reflective
    preferred_formats: list[str] = Field(default_factory=list)
    avg_reading_time_ratio: float = 0.5


# ======== 维度3：易错点偏好 ========
class ErrorPattern(BaseModel):
    type: str = ""
    detail: str = ""
    frequency: int = 0


class ErrorPatterns(BaseModel):
    common_mistakes: list[ErrorPattern] = Field(default_factory=list)
    error_prone_topics: list[str] = Field(default_factory=list)


# ======== 维度4：认知水平（Bloom分类） ========
class CognitiveLevel(BaseModel):
    remember: int = 0
    understand: int = 0
    apply: int = 0
    analyze: int = 0
    evaluate: int = 0
    create: int = 0
    thinking_style: str = ""  # 入门问卷采集：先记忆/理解原理/动手尝试/对比分析


# ======== 维度5：兴趣倾向 ========
class InterestTendency(BaseModel):
    directions: list[str] = Field(default_factory=list)
    engagement_topics: list[str] = Field(default_factory=list)
    skip_topics: list[str] = Field(default_factory=list)


# ======== 维度6：学习节奏 ========
class LearningPace(BaseModel):
    avg_session_minutes: int = 0
    completion_speed: str = "未知"  # 快 | 中等 | 慢
    daily_available_hours: str = ""  # 入门问卷采集：<30min / 30min-1h / 1-2h / >2h
    peak_hours: list[str] = Field(default_factory=list)
    streak_days: int = 0


# ======== 维度7：目标导向 ========
class LearningGoal(BaseModel):
    primary: str = ""
    secondary: str = ""
    timeline: str = ""
    target_projects: list[str] = Field(default_factory=list)


# ======== 完整画像 ========
class StudentProfile(BaseModel):
    knowledge_base: KnowledgeBase = Field(default_factory=KnowledgeBase)
    learning_style: LearningStyle = Field(default_factory=LearningStyle)
    error_patterns: ErrorPatterns = Field(default_factory=ErrorPatterns)
    cognitive_level: CognitiveLevel = Field(default_factory=CognitiveLevel)
    interest_tendency: InterestTendency = Field(default_factory=InterestTendency)
    learning_pace: LearningPace = Field(default_factory=LearningPace)
    learning_goal: LearningGoal = Field(default_factory=LearningGoal)


class ProfileResponse(BaseModel):
    profile: StudentProfile
    last_updated: str = ""
    confidence: float = 0.0


class ProfileHistoryItem(BaseModel):
    time: str
    level: str = ""
    score: dict = Field(default_factory=dict)


class KeyExchange(BaseModel):
    round_num: int
    user_said: str
    system_extracted: str
    dimension_affected: str
