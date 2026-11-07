"""SSE 连接管理器 — 管理流式推送连接和消息队列"""

import asyncio
import json
import uuid
from typing import AsyncGenerator


class SSEManager:
    """管理所有 SSE 连接"""

    def __init__(self):
        self._connections: dict[str, asyncio.Queue] = {}

    def create_connection(self) -> tuple[str, asyncio.Queue]:
        """创建新的 SSE 连接，返回 (connection_id, queue)"""
        conn_id = str(uuid.uuid4())[:8]
        queue: asyncio.Queue = asyncio.Queue()
        self._connections[conn_id] = queue
        return conn_id, queue

    def remove_connection(self, conn_id: str):
        """移除连接"""
        self._connections.pop(conn_id, None)

    async def send_event(self, conn_id: str, event: str, data: dict):
        """向指定连接发送事件"""
        queue = self._connections.get(conn_id)
        if queue:
            await queue.put({"event": event, "data": data})

    async def close_connection(self, conn_id: str):
        """关闭连接"""
        await self.send_event(conn_id, "done", {"message": "closed"})
        self.remove_connection(conn_id)


# 全局单例
sse_manager = SSEManager()


async def format_sse(event: str, data: dict) -> str:
    """将事件格式化为 SSE 标准字符串"""
    data_str = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {data_str}\n\n"


async def sse_generator(conn_id: str) -> AsyncGenerator[str, None]:
    """SSE 事件生成器 — FastAPI StreamingResponse 使用"""
    queue = sse_manager._connections.get(conn_id)
    if not queue:
        yield await format_sse("error", {"message": "无效连接"})
        return

    try:
        while True:
            msg = await queue.get()
            yield await format_sse(msg["event"], msg["data"])
            if msg["event"] == "done":
                break
    except asyncio.CancelledError:
        pass
    finally:
        sse_manager.remove_connection(conn_id)
