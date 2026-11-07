"""通用 API 请求/响应 Schema"""

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    user_id: str = ""
    course: str = "Python程序设计"


class CreateSessionResponse(BaseModel):
    session_id: str
    greeting: str


class SessionInfo(BaseModel):
    session_id: str
    user_name: str = ""
    profile_summary: dict = Field(default_factory=dict)
    last_active: str = ""


class ChatRequest(BaseModel):
    session_id: str
    message: str
    context: dict = Field(default_factory=dict)


class SSEEvent(BaseModel):
    event: str
    data: dict


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    user_id: str
    username: str
    display_name: str = ""
    token: str = ""
