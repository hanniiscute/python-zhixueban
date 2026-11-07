"""全局配置"""

import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# 当前激活课程
ACTIVE_COURSE = "python"

# 路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSE_CONFIG_PATH = os.path.join(BASE_DIR, "config", "courses")
DATA_DIR = os.path.join(BASE_DIR, "data")
# FAISS 向量索引路径（替代 ChromaDB）
FAISS_INDEX_DIR = os.path.join(DATA_DIR, "faiss")
FAISS_PATH_INDEX_FILE = os.path.join(FAISS_INDEX_DIR, "path_index.faiss")
FAISS_EXERCISE_INDEX_FILE = os.path.join(FAISS_INDEX_DIR, "exercise_index.faiss")
FAISS_PATH_META_FILE = os.path.join(FAISS_INDEX_DIR, "path_metadata.pkl")
FAISS_EXERCISE_META_FILE = os.path.join(FAISS_INDEX_DIR, "exercise_metadata.pkl")

# 知识库数据源目录
KNOWLEDGE_DATA_DIR = os.path.join(DATA_DIR, "knowledge_base")
PPT_DIR = os.path.join(KNOWLEDGE_DATA_DIR, "ppts")

# FAISS 检索参数
EMBEDDING_DIM = 256  # 与离线 TF-IDF+SVD 模型一致
DEFAULT_TOP_K = 5
FAISS_OVERFETCH = 20

# 离线 Embedding 模型路径（从 trea 复制）
MODELS_DIR = os.path.join(DATA_DIR, "models")
PATH_MODEL_DIR = os.path.join(MODELS_DIR, "path_vectorizer")
EXERCISE_VECTORIZER_PATH = os.path.join(MODELS_DIR, "exercise_vectorizer.pkl")

# MySQL 数据库配置
MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "123456")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "agents")
DATABASE_URL = (
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
)

# 讯飞星火 API 配置
SPARK_APP_ID = os.environ.get("SPARK_APP_ID", "")
SPARK_API_SECRET = os.environ.get("SPARK_API_SECRET", "")
SPARK_API_KEY = os.environ.get("SPARK_API_KEY", "")

# OpenAI 兼容 HTTP 接口（spark-api-open），鉴权 Bearer key:secret
SPARK_API_BASE = os.environ.get("SPARK_API_BASE", "https://spark-api-open.xf-yun.com/v1")
SPARK_MODEL = os.environ.get("SPARK_MODEL", "4.0Ultra")
# 星辰 MaaS 平台（maas-api.cn-huabei-1.xf-yun.com）使用独立 API Key，设置后优先于 key:secret
SPARK_BEARER_TOKEN = os.environ.get("SPARK_BEARER_TOKEN", "")
# 思考模式：X2.5 系列模型默认"先思考再回答"，首字延迟 3 秒+；默认关闭（设 true 打开）
SPARK_THINKING = os.environ.get("SPARK_THINKING", "false").lower() in ("true", "1", "yes")

# 旧版 WebSocket 地址已弃用（2026-10-03 起改用 OpenAI 兼容 HTTP 接口，见 SPARK_API_BASE）

# 讯飞 Embedding 服务
# 端点: emb-cn-huabei-1.xf-yun.com（旧版HTTP协议，已验证可用）
# 鉴权: Bearer {api_key}:{api_secret}
# 向量维度: 2560，输入限制: 2048 token
# 参考: https://www.xfyun.cn/doc/spark/embedding_api.html
SPARK_EMBEDDING_URL = "https://emb-cn-huabei-1.xf-yun.com/"

# 服务配置
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
