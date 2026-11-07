"""Pydantic 数据模型 — 学习路径"""

from pydantic import BaseModel, Field


class PhaseTopic(BaseModel):
    topic_id: str
    title: str
    status: str = "locked"  # locked | available | in_progress | completed
    resources: list[str] = Field(default_factory=list)


class LearningPhase(BaseModel):
    order: int
    title: str
    status: str = "locked"  # locked | in_progress | completed
    progress: float = 0.0
    topics: list[PhaseTopic] = Field(default_factory=list)
    estimated_hours: float = 0
    actual_hours: float = 0


class LearningPathResponse(BaseModel):
    path_id: str = ""
    generated_at: str = ""
    updated_at: str = ""
    phases: list[LearningPhase] = Field(default_factory=list)
    recommended_next: dict = Field(default_factory=dict)


class RecommendationItem(BaseModel):
    resource_id: str
    title: str
    type: str
    reason: str = ""
    priority: str = "medium"
    match_score: float = 0.0


class RecommendationsResponse(BaseModel):
    recommendations: list[RecommendationItem] = Field(default_factory=list)


class CompleteTopicRequest(BaseModel):
    topic: str
    resource_id: str
    time_spent_minutes: int = 0
    self_evaluation: str = ""


class StartTopicRequest(BaseModel):
    topic: str


class StartPracticeRequest(BaseModel):
    topic: str
    force: bool = False   # True = 强制重新生成（"换一批"），否则优先复用同主题已有题目


class SubmitPracticeRequest(BaseModel):
    topic: str
    correct: int
    total: int
    resource_id: str = ""
    time_spent_minutes: int = 0
    # 错题明细（前端判分后带上）：[{stem, options, answer, user_answer, explanation}]
    # 缺省为空 = 老版本前端，此时只记分数不落错题
    mistakes: list = Field(default_factory=list)


class PracticeSubmitResponse(BaseModel):
    passed: bool
    score_pct: float
    path_updated: bool
    message: str = ""
