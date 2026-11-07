"""RAG 层 — FAISS 向量检索客户端封装

管理两个独立的 FAISS 索引：
- path_index: 学习路径知识点 + PPT 教材内容 (256-dim)
- exercise_index: 习题库 (256-dim)

索引类型: IndexFlatIP (内积，归一化后等价余弦相似度)
元数据: 通过 pickle 文件并行存储
"""

import os
import pickle

import numpy as np
import faiss
from config.settings import (
    FAISS_INDEX_DIR, FAISS_PATH_INDEX_FILE, FAISS_EXERCISE_INDEX_FILE,
    FAISS_PATH_META_FILE, FAISS_EXERCISE_META_FILE, EMBEDDING_DIM,
    FAISS_OVERFETCH,
)


class FAISSClient:
    """FAISS 封装，管理学习路径和习题双索引"""

    def __init__(self, index_dir: str = FAISS_INDEX_DIR):
        self.index_dir = index_dir
        self.dim = EMBEDDING_DIM  # 256（离线 TF-IDF+SVD）

        # 学习路径索引
        self.path_index: faiss.IndexFlatIP | None = None
        self.path_metadata: list[dict] = []

        # 习题索引
        self.exercise_index: faiss.IndexFlatIP | None = None
        self.exercise_metadata: list[dict] = []

        self._initialized = False

    # ================================================================
    # 生命周期
    # ================================================================

    def initialize(self):
        """从磁盘加载已有索引"""
        os.makedirs(self.index_dir, exist_ok=True)
        loaded_any = False

        if os.path.exists(FAISS_PATH_INDEX_FILE) and os.path.exists(FAISS_PATH_META_FILE):
            try:
                with open(FAISS_PATH_INDEX_FILE, "rb") as f:
                    data = pickle.load(f)  # np.ndarray
                    self.path_index = faiss.deserialize_index(data)
                with open(FAISS_PATH_META_FILE, "rb") as f:
                    self.path_metadata = pickle.load(f)
                print(f"[FAISS] 已加载学习路径索引: {self.path_index.ntotal} 条")
                loaded_any = True
            except Exception as e:
                print(f"[FAISS] 加载学习路径索引失败: {e}")

        if os.path.exists(FAISS_EXERCISE_INDEX_FILE) and os.path.exists(FAISS_EXERCISE_META_FILE):
            try:
                with open(FAISS_EXERCISE_INDEX_FILE, "rb") as f:
                    data = pickle.load(f)
                    self.exercise_index = faiss.deserialize_index(data)
                with open(FAISS_EXERCISE_META_FILE, "rb") as f:
                    self.exercise_metadata = pickle.load(f)
                print(f"[FAISS] 已加载习题索引: {self.exercise_index.ntotal} 条")
                loaded_any = True
            except Exception as e:
                print(f"[FAISS] 加载习题索引失败: {e}")

        self._initialized = loaded_any

    def is_ready(self) -> bool:
        return self._initialized

    # ================================================================
    # 构建索引
    # ================================================================

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        """L2 归一化，使 IndexFlatIP 的内积等价于余弦相似度"""
        faiss.normalize_L2(vectors)
        return vectors

    def build_path_index(self, vectors: list[list[float]], metadata: list[dict]):
        """构建学习路径 FAISS 索引"""
        vecs = np.array(vectors, dtype=np.float32)
        actual_dim = vecs.shape[1]
        self._normalize(vecs)
        self.path_index = faiss.IndexFlatIP(actual_dim)
        self.path_index.add(vecs)
        self.path_metadata = metadata
        print(f"[FAISS] 学习路径索引使用 {actual_dim} 维向量")

    def build_exercise_index(self, vectors: list[list[float]], metadata: list[dict]):
        """构建习题 FAISS 索引"""
        vecs = np.array(vectors, dtype=np.float32)
        actual_dim = vecs.shape[1]
        self._normalize(vecs)
        self.exercise_index = faiss.IndexFlatIP(actual_dim)
        self.exercise_index.add(vecs)
        self.exercise_metadata = metadata
        print(f"[FAISS] 习题索引使用 {actual_dim} 维向量")

    # ================================================================
    # 检索
    # ================================================================

    def _search_index(self, index, metadata_list, query_vec, k, filters):
        """在单个索引中检索，带元数据过滤（overfetch + Python filter）"""
        if index is None or index.ntotal == 0:
            return []

        fetch_k = min(max(k, FAISS_OVERFETCH), index.ntotal)
        query_np = np.array([query_vec], dtype=np.float32)
        self._normalize(query_np)

        distances, indices = index.search(query_np, fetch_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(metadata_list):
                continue
            meta = metadata_list[idx]
            # 元数据过滤
            if filters:
                if "difficulty" in filters and meta.get("difficulty") != filters["difficulty"]:
                    continue
                if "chapter" in filters and meta.get("chapter") != filters["chapter"]:
                    continue
                if "path_name" in filters and meta.get("path_name") != filters["path_name"]:
                    continue
                if "source" in filters and meta.get("source") != filters["source"]:
                    continue
            results.append({
                "content": meta.get("text", meta.get("description", "")),
                "metadata": meta,
                "score": float(dist),
            })
            if len(results) >= k:
                break

        return results

    def search_paths(self, query_vec, k=5, filters=None):
        """检索学习路径"""
        return self._search_index(self.path_index, self.path_metadata, query_vec, k, filters)

    def search_exercises(self, query_vec, k=5, filters=None):
        """检索习题"""
        return self._search_index(self.exercise_index, self.exercise_metadata, query_vec, k, filters)

    def search_all(self, query_vec, k=5, filters=None):
        """合并检索两个索引，按分数排序取 top-k"""
        path_results = self.search_paths(query_vec, k=k, filters=filters)
        exercise_results = self.search_exercises(query_vec, k=k, filters=filters)
        merged = path_results + exercise_results
        merged.sort(key=lambda x: x["score"], reverse=True)
        return merged[:k]

    # ================================================================
    # 持久化
    # ================================================================

    def save(self):
        """保存索引和元数据到磁盘（序列化为 numpy array 后 pickle 保存）"""
        os.makedirs(self.index_dir, exist_ok=True)
        if self.path_index is not None:
            data = faiss.serialize_index(self.path_index)  # returns np.ndarray
            with open(FAISS_PATH_INDEX_FILE, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            with open(FAISS_PATH_META_FILE, "wb") as f:
                pickle.dump(self.path_metadata, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"[FAISS] 学习路径索引已保存 ({self.path_index.ntotal} 条)")
        if self.exercise_index is not None:
            data = faiss.serialize_index(self.exercise_index)
            with open(FAISS_EXERCISE_INDEX_FILE, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            with open(FAISS_EXERCISE_META_FILE, "wb") as f:
                pickle.dump(self.exercise_metadata, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"[FAISS] 习题索引已保存 ({self.exercise_index.ntotal} 条)")


# 全局单例
faiss_client = FAISSClient()
