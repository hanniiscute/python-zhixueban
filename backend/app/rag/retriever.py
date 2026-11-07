"""RAG 检索器 — 画像驱动的知识检索 (FAISS 后端)"""

from app.core import vocab
from app.rag.faiss_client import faiss_client
from app.rag.offline_embedder import offline_embedder


class Retriever:
    """知识检索器，基于 FAISS 双索引 + 学生画像过滤"""

    # 画像知识水平 → 知识库难度 映射（统一由 app.core.vocab 提供；
    # 历史实现用「零基础/入门/进阶/熟练」，与问卷写入的中文标签对不上，
    # 导致所有用户都被当成默认档按「简单」过滤，把中等/进阶教材全滤掉）
    LEVEL_TO_DIFFICULTY = vocab.LEVEL_TO_DIFFICULTY

    def __init__(self):
        self.client = None

    def initialize(self):
        """初始化：加载 FAISS 索引"""
        self.client = faiss_client
        if not self.client.is_ready():
            self.client.initialize()
        if self.client.is_ready():
            print("[Retriever] FAISS 检索器初始化完成")
        else:
            print("[Retriever] FAISS 索引未就绪，检索将返回空结果（系统仍可正常对话）")

    def is_ready(self) -> bool:
        return self.client is not None and self.client.is_ready()

    # ================================================================
    # 检索
    # ================================================================

    def retrieve(self, query: str, top_k: int = 5, profile: dict = None) -> list[dict]:
        """画像驱动的知识检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            profile: 学生画像 dict，用于难度过滤

        Returns:
            list[dict]: [{"content": ..., "metadata": {...}, "score": float}, ...]
        """
        if not self.is_ready():
            return []

        # 1. 离线嵌入查询 (TF-IDF+SVD 256维)
        query_vec = offline_embedder.embed_query(query)
        if not query_vec or all(v == 0 for v in query_vec):
            return []

        # 2. 构建过滤条件
        filters = None
        if profile:
            level = profile.get("knowledge_base", {}).get("level")
            difficulty = vocab.level_to_difficulty(level)
            filters = {"difficulty": difficulty}

        # 3. FAISS 检索
        results = self.client.search_all(query_vec, k=top_k, filters=filters)

        # 4. 去重 (同一内容只保留最高分)
        seen = set()
        unique_results = []
        for r in results:
            content_key = r["content"][:100]  # 用前 100 字符做去重键
            if content_key not in seen:
                seen.add(content_key)
                unique_results.append(r)

        return unique_results[:top_k]

    def retrieve_exercises_only(self, query: str, top_k: int = 15) -> list[dict]:
        """只从习题库检索，不混入学习路径和PPT内容"""
        if not self.is_ready():
            return []

        query_vec = offline_embedder.embed_query(query)
        if not query_vec or all(v == 0 for v in query_vec):
            return []

        return self.client.search_exercises(query_vec, k=top_k)

    def retrieve_exercises_context(self, query: str, top_k: int = 15) -> str:
        """只检索习题，格式化为题目列表供 quiz_gen 使用"""
        docs = self.retrieve_exercises_only(query, top_k=top_k)
        if not docs:
            return ""

        parts = []
        for i, doc in enumerate(docs):
            meta = doc.get("metadata", {})
            parts.append(
                f"题库{i + 1} [ID:{meta.get('id', '?')}] "
                f"类型:{meta.get('qtype', '?')} "
                f"难度:{meta.get('difficulty', '?')} "
                f"章节:{meta.get('chapter', '?')}\n"
                f"{doc['content']}"
            )
        return "\n\n---\n\n".join(parts)

    # ================================================================
    # 上下文拼接
    # ================================================================

    def retrieve_context(self, query: str, profile: dict = None, top_k: int = 5) -> str:
        """检索并拼接为 Prompt 上下文，用于注入 {{retrieved_chunks}}

        Returns:
            格式化字符串；无结果时返回空字符串
        """
        docs = self.retrieve(query, top_k=top_k, profile=profile)
        if not docs:
            return ""

        context_parts = []
        for i, doc in enumerate(docs):
            meta = doc.get("metadata", {})
            source = meta.get("source", "未知来源")
            if source == "learning_paths":
                label = (
                    f"[参考{i + 1} - 知识点: {meta.get('node_name', '')}"
                    f" | 章节: {meta.get('chapter', '')}"
                    f" | 难度: {meta.get('difficulty', '')}]"
                )
            elif source == "exercises":
                label = (
                    f"[参考{i + 1} - 习题: {meta.get('id', '')}"
                    f" | 类型: {meta.get('qtype', '')}"
                    f" | 难度: {meta.get('difficulty', '')}]"
                )
            elif source == "ppt":
                label = f"[参考{i + 1} - 教材: {meta.get('chapter', '')}]"
            else:
                label = f"[参考{i + 1} - {source}]"

            context_parts.append(f"{label}\n{doc['content']}")

        return "\n\n---\n\n".join(context_parts)


retriever = Retriever()
