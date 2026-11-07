"""个性化学习智能体系统 — FastAPI 入口"""

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()  # 加载 .env 中的密钥（讯飞星火 API 等）

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import CORS_ORIGINS, DATA_DIR
from app.db.sqlite_client import db
from app.rag.faiss_client import faiss_client
from app.rag.embedder import spark_embedder
from app.rag.retriever import retriever
from app.api.session import router as session_router
from app.api.chat import router as chat_router
from app.api.profile import router as profile_router
from app.api.resources import router as resources_router
from app.api.learning_path import router as learning_path_router
from app.api.tutoring import router as tutoring_router
from app.api.evaluation import router as evaluation_router
from app.api.report import router as report_router
from app.api.auth import router as auth_router

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库与检索索引

    （原用 @app.on_event("startup")，该写法在新版 FastAPI 已弃用，改为 lifespan）
    """
    # 初始化数据库表
    db.init_tables()
    print("[启动] MySQL 数据库表初始化完成")

    # 初始化 FAISS 向量索引
    faiss_client.initialize()

    # 初始化离线 Embedding 模型（TF-IDF+SVD 256维）
    from app.rag.offline_embedder import offline_embedder
    offline_embedder.load()

    # 初始化讯飞 Embedder（仅用于意图识别）
    spark_embedder.configure_from_settings()

    # 初始化检索器
    retriever.initialize()
    print("[启动] RAG 检索器初始化完成")

    print(f"[启动] 服务已就绪，访问 http://localhost:8000/docs 查看 API 文档")
    yield


# 创建 FastAPI 应用
app = FastAPI(
    title="个性化学习智能体系统",
    description="高等教育个性化学习资源体系 — 基于多智能体协同",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局认证中间件：/api/* （除 /api/auth/*）必须携带有效签名 token
@app.middleware("http")
async def auth_middleware(request, call_next):
    path = request.url.path
    # 豁免：认证接口本身、CORS 预检、非 API 路径
    if (not path.startswith("/api")
            or path.startswith("/api/auth")
            or request.method == "OPTIONS"):
        return await call_next(request)

    from fastapi.responses import JSONResponse
    from app.core.token_utils import verify_token

    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    user_id = verify_token(token)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期，请重新登录"})

    # 会话归属校验：扫描 URL 的**所有**路径段，只要命中 sess_ 前缀就校验归属。
    # 不能只看第 3 段 —— /api/chat/history/{session_id} 的第 3 段是 "history"，
    # 旧写法会被直接绕过，导致任意登录用户可读他人会话。
    from app.db.sqlite_client import db as _db
    session_ids = [p for p in path.split("/") if p.startswith("sess_")]
    for sid in session_ids:
        row = _db.fetch_one("SELECT user_id FROM sessions WHERE id = %s", (sid,))
        if row and row["user_id"] != user_id:
            return JSONResponse(status_code=403, content={"detail": "无权访问该会话"})

    request.state.user_id = user_id
    return await call_next(request)

# 挂载路由
app.include_router(auth_router)
app.include_router(session_router)
app.include_router(chat_router)
app.include_router(profile_router)
app.include_router(resources_router)
app.include_router(learning_path_router)
app.include_router(tutoring_router)
app.include_router(evaluation_router)
app.include_router(report_router)


@app.get("/")
def root():
    return {
        "service": "个性化学习智能体系统",
        "version": "1.0.0",
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
