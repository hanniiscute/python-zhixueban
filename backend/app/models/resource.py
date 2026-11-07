"""Pydantic 数据模型 — 学习资源"""

from pydantic import BaseModel, Field


class ResourceMeta(BaseModel):
    difficulty: str = "入门"
    estimated_minutes: int = 15
    word_count: int = 0
    has_diagram: bool = False
    prerequisites: list[str] = Field(default_factory=list)


class ResourceItem(BaseModel):
    resource_id: str
    type: str  # document | mindmap | quiz | notebook | reading
    title: str
    topic: str = ""
    format: str = "markdown"
    generated_by: str = ""
    created_at: str = ""
    metadata: ResourceMeta = Field(default_factory=ResourceMeta)
    user_rating: float = 0.0
    learned: bool = False          # 该主题是否已学完（和学习路径进度联动）
    type_label: str = ""           # 资料类型中文名（讲义/思维导图/练习题/代码实操）


class ResourceListResponse(BaseModel):
    total: int
    page: int
    resources: list[ResourceItem]
    duplicates_merged: int = 0     # 自动折叠掉的重复份数（同主题同类型只留最新一份）


class ResourceDetail(BaseModel):
    resource_id: str
    type: str
    title: str
    content: str = ""
    topic: str = ""
    difficulty: str = "入门"
    prerequisites: list[str] = Field(default_factory=list)
    references: list[dict] = Field(default_factory=list)
    related_resources: list[str] = Field(default_factory=list)
    created_at: str = ""


class ResourceFeedbackRequest(BaseModel):
    rating: int = 0  # 1-5
    helpful: bool = True
    difficulty_feedback: str = "正好"  # 太难 | 正好 | 太简单
    comment: str = ""
