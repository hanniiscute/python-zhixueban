"""离线 Embedding — TF-IDF + SVD（从 trea 继承的预训练模型）

纯离线运行，无需 API 调用。学习路径用 TF-IDF+SVD+L2 归一化 (256维)，
习题和查询共用同一个模型。
"""

import os
import pickle
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from config.settings import PATH_MODEL_DIR


class OfflineEmbedder:
    """TF-IDF + SVD + L2 归一化 Embedding（学习路径模型，256维）"""

    def __init__(self):
        self.dim: int = 256
        self.vectorizer: TfidfVectorizer = None
        self.svd: TruncatedSVD = None
        self._loaded = False

    # ================================================================
    # 加载
    # ================================================================

    def load(self, model_dir: str = PATH_MODEL_DIR):
        """从磁盘加载预训练模型"""
        if not os.path.exists(model_dir):
            print(f"[OfflineEmbedder] 模型目录不存在: {model_dir}")
            return False

        try:
            dim_path = os.path.join(model_dir, "dim.txt")
            with open(dim_path, "r") as f:
                self.dim = int(f.read().strip())

            tfidf_path = os.path.join(model_dir, "tfidf.pkl")
            with open(tfidf_path, "rb") as f:
                self.vectorizer = pickle.load(f)

            svd_path = os.path.join(model_dir, "svd.pkl")
            with open(svd_path, "rb") as f:
                self.svd = pickle.load(f)

            self._loaded = True
            print(f"[OfflineEmbedder] 模型加载完成: {self.dim}维 TF-IDF+SVD")
            return True
        except Exception as e:
            print(f"[OfflineEmbedder] 模型加载失败: {e}")
            return False

    def is_ready(self) -> bool:
        return self._loaded

    @property
    def actual_dim(self) -> int:
        """返回 SVD 实际输出的向量维度"""
        if self.svd is not None:
            return self.svd.n_components
        return self.dim

    # ================================================================
    # 嵌入
    # ================================================================

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量文档嵌入（索引时使用）"""
        if not self._loaded:
            return [[0.0] * self.actual_dim for _ in texts]

        tfidf = self.vectorizer.transform(texts)
        vecs = self.svd.transform(tfidf)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normalized = (vecs / norms).astype(np.float32)
        return normalized.tolist()

    def embed_query(self, text: str) -> list[float]:
        """单条查询嵌入"""
        result = self.embed_documents([text])
        return result[0] if result else [0.0] * self.actual_dim

    # ================================================================
    # 重新训练（sklearn 版本迁移用）
    # ================================================================

    def fit(self, corpus: list[str], model_dir: str = PATH_MODEL_DIR, dim: int = 256) -> bool:
        """在语料上用**当前 sklearn 版本**重新训练 TF-IDF+SVD 模型并保存。

        用途：模型 pkl 由旧版 sklearn (1.2.0) 训练，换环境后加载会有
        InconsistentVersionWarning 且行为可能异常。用新语料重训即可消除。

        Args:
            corpus: 训练语料（知识库全部文本块）
            model_dir: 模型保存目录
            dim: 目标 SVD 维度（样本/特征不足时会自动降低）

        Returns:
            是否训练成功
        """
        if len(corpus) < 50:
            print(f"[OfflineEmbedder] 语料太少({len(corpus)}条)，放弃训练")
            return False

        print(f"[OfflineEmbedder] 用当前 sklearn 在 {len(corpus)} 条语料上训练 TF-IDF+SVD...")
        # ⚠️ char_wb 字符 n-gram：无分词器也能处理中文（与原预训练模型配置一致）
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3), max_features=5000)
        tfidf = vectorizer.fit_transform(corpus)

        n_comp = min(dim, tfidf.shape[1] - 1, tfidf.shape[0] - 1)
        n_comp = max(16, n_comp)
        svd = TruncatedSVD(n_components=n_comp)
        svd.fit(tfidf)

        explained = float(svd.explained_variance_ratio_.sum())
        print(f"[OfflineEmbedder] 训练完成: {n_comp}维, 方差解释率 {explained:.1%}")

        os.makedirs(model_dir, exist_ok=True)
        with open(os.path.join(model_dir, "tfidf.pkl"), "wb") as f:
            pickle.dump(vectorizer, f)
        with open(os.path.join(model_dir, "svd.pkl"), "wb") as f:
            pickle.dump(svd, f)
        with open(os.path.join(model_dir, "dim.txt"), "w") as f:
            f.write(str(n_comp))

        # 训练完直接热替换当前模型
        self.vectorizer = vectorizer
        self.svd = svd
        self.dim = n_comp
        self._loaded = True
        print(f"[OfflineEmbedder] 新模型已保存到 {model_dir}")
        return True


# 全局单例
offline_embedder = OfflineEmbedder()
