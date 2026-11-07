"""讯飞星火大模型客户端 — OpenAI 兼容 HTTP 接口（SSE 流式）"""

import asyncio
import json
import queue
import threading
import requests
from config.settings import (
    SPARK_API_KEY,
    SPARK_API_SECRET,
    SPARK_API_BASE,
    SPARK_MODEL,
    SPARK_BEARER_TOKEN,
    SPARK_THINKING,
)

# 连接复用：避免每条消息都重新做 TLS 握手（省 200-500ms）
_http = requests.Session()


class SparkLLMClient:
    """星火大模型客户端（OpenAI 兼容 HTTP 接口，Bearer key:secret 鉴权）

    相比旧版 WebSocket 协议：
    - 无需手工拼 HMAC 鉴权 URL，密钥错/权限错都能拿到明确报错
    - 模型名在 .env 里可配（SPARK_MODEL），领了哪个模型的试用包就填哪个
    """

    def __init__(self):
        self.api_base = SPARK_API_BASE
        self.model = SPARK_MODEL
        # MaaS 平台用独立 Bearer Key；未配置时用星火开放平台的 key:secret
        self.token = SPARK_BEARER_TOKEN or f"{SPARK_API_KEY}:{SPARK_API_SECRET}"

    @staticmethod
    def _friendly_error(msg: str) -> str:
        """把服务端报错翻译成人话"""
        msg = str(msg)
        if "AppIdNoAuthError" in msg:
            return (
                "星火模型未授权：请在讯飞控制台（console.xfyun.cn）为该应用领取模型的免费试用包后重试"
            )
        if "HMAC" in msg or "apikey not found" in msg:
            return "星火密钥无效：请检查 .env 里的 SPARK_API_KEY / SPARK_API_SECRET"
        if "invalid param model" in msg:
            return f"模型名不可用：当前配置的模型 {msg}，请检查 .env 里的 SPARK_MODEL"
        return msg

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def _body(self, messages: list[dict], temperature: float, max_tokens: int, stream: bool) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        # X2.5 系列是"先思考再回答"的模型，思考阶段消耗 3 秒以上的首字延迟；
        # 默认关闭思考（.env 设 SPARK_THINKING=true 可打开，回答质量略升但明显变慢）
        if not SPARK_THINKING:
            body["thinking"] = {"type": "disabled"}
        return body

    async def chat_stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096):
        """流式对话 — HTTP SSE，后台线程读流 + 队列，async 侧逐段产出"""
        url = f"{self.api_base}/chat/completions"
        result_queue: queue.Queue = queue.Queue()

        def run():
            try:
                resp = _http.post(
                    url,
                    headers=self._headers(),
                    json=self._body(messages, temperature, max_tokens, stream=True),
                    stream=True,
                    timeout=(15, 300),
                )
                if resp.status_code != 200:
                    try:
                        err = resp.json().get("error", {}).get("message", "") or resp.text[:150]
                    except Exception:
                        err = f"HTTP {resp.status_code}"
                    result_queue.put({"error": self._friendly_error(err), "done": True})
                    return

                resp.encoding = "utf-8"  # SSE 无 charset 时 requests 默认 Latin-1，中文会乱码
                for raw in resp.iter_lines(decode_unicode=True):
                    if not raw or not raw.startswith("data:"):
                        continue
                    data = raw[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        d = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    if "error" in d:
                        err = d["error"].get("message", "未知错误")
                        result_queue.put({"error": self._friendly_error(err), "done": True})
                        return
                    # 流式模式错误格式: {"code":11200,"message":"AppIdNoAuthError",...}
                    if d.get("code") not in (None, 0) and not d.get("choices"):
                        result_queue.put(
                            {"error": self._friendly_error(d.get("message", "未知错误")), "done": True}
                        )
                        return

                    choices = d.get("choices") or [{}]
                    content = choices[0].get("delta", {}).get("content", "")
                    if content:
                        result_queue.put({"content": content, "done": False})
                    if choices[0].get("finish_reason"):
                        break

                result_queue.put({"content": "", "done": True})
            except Exception as e:
                result_queue.put({"error": self._friendly_error(str(e)[:150]), "done": True})

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        while True:
            try:
                item = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: result_queue.get(timeout=150)
                )
            except queue.Empty:
                yield {"error": "响应超时，请重试", "done": True}
                break
            yield item
            if item.get("done"):
                break

        thread.join(timeout=5)

    def chat_sync(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        """同步对话（非流式），供后端内部生成任务使用"""
        url = f"{self.api_base}/chat/completions"
        try:
            resp = _http.post(
                url,
                headers=self._headers(),
                json=self._body(messages, temperature, max_tokens, stream=False),
                timeout=180,
            )
            if resp.status_code != 200:
                try:
                    err = resp.json().get("error", {}).get("message", "") or resp.text[:150]
                except Exception:
                    err = f"HTTP {resp.status_code}"
                return f"[星火API错误] {self._friendly_error(err)}"

            d = resp.json()
            if "error" in d:
                return f"[星火API错误] {self._friendly_error(d['error'].get('message', ''))}"

            text = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
            return text if text else "[星火API] 未收到回复，请重试"
        except Exception as e:
            return f"[星火API错误] {self._friendly_error(str(e)[:150])}"


# 全局单例
spark_llm = SparkLLMClient()
