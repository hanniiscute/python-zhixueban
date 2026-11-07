"""讯飞 Embedding API 封装 — 文本转向量（2560维）

已验证可用: emb-cn-huabei-1.xf-yun.com，Bearer 鉴权
"""

import base64
import json

import numpy as np
import requests
from config.settings import (
    SPARK_APP_ID,
    SPARK_API_KEY,
    SPARK_API_SECRET,
    SPARK_EMBEDDING_URL,
)


class SparkEmbedder:
    """讯飞星火 Embedding 服务

    端点: emb-cn-huabei-1.xf-yun.com
    鉴权: Bearer {api_key}:{api_secret}
    向量维度: 2560
    输入限制: 2048 token
    """

    def __init__(self):
        self.app_id = ""
        self.api_key = ""
        self.api_secret = ""
        self._configured = False
        self._fail_count = 0      # 连续失败计数
        self._disabled = False    # 熔断：连续失败后本进程内不再调用，避免每条消息白等超时

    # ================================================================
    # 配置
    # ================================================================

    def configure_from_settings(self):
        """从 settings 读取密钥并配置"""
        self.app_id = SPARK_APP_ID
        self.api_key = SPARK_API_KEY
        self.api_secret = SPARK_API_SECRET
        self._configured = bool(self.app_id and self.api_key and self.api_secret)
        if self._configured:
            print(f"[Embedder] 配置完成，app_id={self.app_id}")
        else:
            print("[Embedder] 未配置密钥，将返回占位向量")

    def is_ready(self) -> bool:
        return self._configured

    # ================================================================
    # 请求构建
    # ================================================================

    def _build_body(self, text: str, domain: str = "query") -> dict:
        """构建请求体（旧版HTTP协议格式）

        domain: "query" 用于查询, "para" 用于文档
        """
        # 组装 messages JSON
        text_content = json.dumps(
            {"messages": [{"content": text, "role": "user"}]},
            ensure_ascii=False,
        )
        # Base64 编码
        text_base64 = base64.b64encode(text_content.encode("utf-8")).decode("utf-8")

        return {
            "header": {
                "app_id": self.app_id,
                "uid": "learner_001",
                "status": 3,
            },
            "parameter": {
                "emb": {
                    "domain": domain,
                    "feature": {
                        "encoding": "utf8",
                        "compress": "raw",
                        "format": "plain",
                    },
                }
            },
            "payload": {
                "messages": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "json",
                    "status": 3,
                    "text": text_base64,
                }
            },
        }

    def _build_auth_header(self) -> str:
        """构建 Authorization header"""
        return f"Bearer {self.api_key}:{self.api_secret}"

    # ================================================================
    # 向量解码
    # ================================================================

    @staticmethod
    def _decode_vector(feature_text: str) -> list[float]:
        """解码 API 返回的 Base64 向量为 float32 数组（2560维）"""
        raw = base64.b64decode(feature_text)
        dt = np.dtype(np.float32)
        dt = dt.newbyteorder("<")  # 小端字节序
        vec = np.frombuffer(raw, dtype=dt)
        return vec.tolist()

    # ================================================================
    # 核心方法
    # ================================================================

    def _call_api(self, text: str, domain: str = "query") -> list[float] | None:
        """调用 Embedding API，返回一个 2560 维向量或 None"""
        if not self._configured or self._disabled:
            return None

        body = self._build_body(text, domain)
        headers = {
            "Content-Type": "application/json",
            "Authorization": self._build_auth_header(),
        }

        try:
            resp = requests.post(
                SPARK_EMBEDDING_URL,
                headers=headers,
                json=body,
                timeout=5,
            )
            result = resp.json()
        except requests.RequestException as e:
            print(f"[Embedder] 网络错误: {e}")
            self._bump_fail()
            return None
        except json.JSONDecodeError:
            print(f"[Embedder] 响应解析失败: {resp.text[:300]}")
            self._bump_fail()
            return None

        code = result.get("header", {}).get("code", -1)
        if code == 0:
            self._fail_count = 0
            feature_text = result["payload"]["feature"]["text"]
            return self._decode_vector(feature_text)
        else:
            msg = result.get("header", {}).get("message", "未知错误")
            print(f"[Embedder] API 返回错误 (code={code}): {msg}")
            self._bump_fail()
            return None

    def _bump_fail(self):
        """连续失败 3 次即熔断：服务不可用时不再拖慢每一条消息（调用方会回退关键词方案）"""
        self._fail_count += 1
        if self._fail_count >= 3 and not self._disabled:
            self._disabled = True
            print("[Embedder] 连续失败 3 次，已熔断 Embedding 调用（重启进程后重试；功能自动回退关键词方案）")

    def embed(self, texts: list[str], doc_mode: bool = True) -> list[list[float]]:
        """将文本列表转为向量列表

        Args:
            texts: 待向量化的文本列表
            doc_mode: True 使用 para 域, False 使用 query 域

        Returns:
            向量列表，每个向量 2560 维；未配置时返回全零占位向量
        """
        if not self._configured:
            return [[0.0] * 2560 for _ in texts]

        domain = "para" if doc_mode else "query"
        vectors = []

        for text in texts:
            vec = self._call_api(text, domain)
            if vec is not None:
                vectors.append(vec)
            else:
                vectors.append([0.0] * 2560)

        return vectors

    def embed_query(self, text: str) -> list[float]:
        """单条查询文本转向量（使用 query 域）"""
        if not self._configured:
            return [0.0] * 2560

        results = self.embed([text], doc_mode=False)
        return results[0] if results else [0.0] * 2560

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量文档转向量（使用 para 域）"""
        return self.embed(texts, doc_mode=True)


# 全局单例
spark_embedder = SparkEmbedder()
