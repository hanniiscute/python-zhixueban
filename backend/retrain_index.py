"""重训向量模型 + 重建 FAISS 索引（一次性维护脚本）

用途：models 下的 pkl 由旧版 sklearn 训练，换环境后加载报警告。
运行: cd backend && python retrain_index.py
流程: 读知识库语料 → 当前 sklearn 重训 TF-IDF+SVD → 重建双 FAISS 索引
"""

from app.rag.indexer import Indexer
from app.rag.offline_embedder import offline_embedder


def main():
    indexer = Indexer()

    # 1. 收集语料（与建索引同一份，保证查询/文档向量空间一致）
    path_texts, _ = indexer.load_learning_paths()
    ex_texts, _ = indexer.load_exercises()
    ppt_texts, _ = indexer.load_ppt_texts()
    corpus = path_texts + ex_texts + ppt_texts
    print(f"[Retrain] 语料共 {len(corpus)} 条")

    # 2. 用当前 sklearn 重训模型（训练完热替换 + 落盘）
    if not offline_embedder.fit(corpus):
        raise SystemExit("[Retrain] 模型训练失败")

    # 3. 用新模型重建 FAISS 索引
    indexer.build_all()


if __name__ == "__main__":
    main()
