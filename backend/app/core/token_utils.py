"""签名 Token 工具 — HMAC-SHA256 签发的带过期令牌

格式: v1.<payload_b64url>.<sig_hex>
payload: user_id|过期时间戳(秒)
密钥: 自动生成并持久化到 backend/data/.token_secret（重启后仍有效）
"""

import base64
import hmac
import hashlib
import secrets
import time
import os

from config.settings import DATA_DIR

_SECRET_FILE = os.path.join(DATA_DIR, ".token_secret")
TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 天有效


def _load_secret() -> str:
    """加载（或首次生成）签名密钥"""
    if os.path.exists(_SECRET_FILE):
        with open(_SECRET_FILE, "r", encoding="utf-8") as f:
            secret = f.read().strip()
            if secret:
                return secret
    secret = secrets.token_hex(32)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_SECRET_FILE, "w", encoding="utf-8") as f:
        f.write(secret)
    return secret


def _sign(data: str) -> str:
    return hmac.new(_load_secret().encode(), data.encode(), hashlib.sha256).hexdigest()


def create_token(user_id: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """为用户签发一个带过期时间的签名 token"""
    expires = int(time.time()) + ttl_seconds
    payload = f"{user_id}|{expires}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"v1.{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str) -> str | None:
    """校验 token；有效返回 user_id，无效/过期/被篡改返回 None"""
    if not token or not token.startswith("v1."):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    _, payload_b64, sig = parts
    # 防篡改：先验签
    if not hmac.compare_digest(_sign(payload_b64), sig):
        return None
    # 还原 payload
    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload = base64.urlsafe_b64decode(payload_b64 + padding).decode()
        user_id, expires_str = payload.rsplit("|", 1)
        expires = int(expires_str)
    except Exception:
        return None
    # 防过期
    if time.time() > expires:
        return None
    return user_id or None
