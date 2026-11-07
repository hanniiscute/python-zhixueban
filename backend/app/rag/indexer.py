"""RAG 索引构建器 — 一次性运行，从数据源构建 FAISS 索引

数据源:
1. knowledge_base/learning_paths.json  — 学习路径知识点 (55+)
2. knowledge_base/exercises.json       — 习题库 (206道)
3. knowledge_base/ppts/*.pptx          — 教材 PPT (11章)

输出:
- data/faiss/path_index.faiss + path_metadata.pkl
- data/faiss/exercise_index.faiss + exercise_metadata.pkl

用法: python -m app.rag.indexer
"""

import json
import os
import sys
import time

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import (
    KNOWLEDGE_DATA_DIR, PPT_DIR, EMBEDDING_DIM, FAISS_INDEX_DIR,
)
from app.rag.offline_embedder import offline_embedder
from app.rag.faiss_client import faiss_client


class Indexer:
    """索引构建器"""

    def __init__(self):
        self.embedder = offline_embedder
        self.client = faiss_client
        self.dim = EMBEDDING_DIM  # 256

    # ================================================================
    # 数据加载
    # ================================================================

    def load_learning_paths(self) -> tuple[list[str], list[dict]]:
        """加载学习路径 JSON，返回 (texts, metadatas)"""
        path = os.path.join(KNOWLEDGE_DATA_DIR, "learning_paths.json")
        if not os.path.exists(path):
            print(f"[Indexer] 未找到学习路径文件: {path}")
            return [], []

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        texts = []
        metadatas = []
        for lp in data.get("learning_paths", []):
            for node in lp.get("nodes", []):
                text = (
                    f"【{node['name']}】{node['description']}\n"
                    f"章节：{node['chapter']} | 预估学时：{node['estimated_hours']}h\n"
                    f"知识点：{'、'.join(node.get('knowledge_points', []))}"
                )
                texts.append(text)
                metadatas.append({
                    "text": text,
                    "node_id": node["id"],
                    "node_name": node["name"],
                    "chapter": node.get("chapter", ""),
                    "path_name": lp.get("path_name", ""),
                    "path_id": lp.get("path_id", ""),
                    "estimated_hours": node.get("estimated_hours", 0),
                    "knowledge_points": ", ".join(node.get("knowledge_points", [])),
                    "qtype": ", ".join(node.get("qtype", [])),
                    "description": node.get("description", ""),
                    "difficulty": node.get("difficulty", "中等"),
                    "target_audience": lp.get("target_audience", ""),
                    "source": "learning_paths",
                })

        print(f"[Indexer] 学习路径: {len(texts)} 条知识点")
        return texts, metadatas

    def load_exercises(self) -> tuple[list[str], list[dict]]:
        """加载习题 JSON"""
        path = os.path.join(KNOWLEDGE_DATA_DIR, "exercises.json")
        if not os.path.exists(path):
            print(f"[Indexer] 未找到习题文件: {path}")
            return [], []

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        texts = []
        metadatas = []
        for ex in data:
            text = f"【{ex['qtype']}】{ex['question']}\n答案：{ex.get('answer', '')}"
            texts.append(text)
            metadatas.append({
                "text": text,
                "id": ex["id"],
                "chapter": ex.get("chapter", ""),
                "qtype": ex.get("qtype", ""),
                "difficulty": ex.get("difficulty", "中等"),
                "source": "exercises",
            })

        print(f"[Indexer] 习题: {len(texts)} 道")
        return texts, metadatas

    def load_ppt_texts(self) -> tuple[list[str], list[dict]]:
        """从 PPT 文件中提取文本并按段落分块"""
        if not os.path.exists(PPT_DIR):
            print(f"[Indexer] PPT 目录不存在: {PPT_DIR}")
            return [], []

        try:
            from pptx import Presentation
        except ImportError:
            print("[Indexer] python-pptx 未安装，跳过 PPT 提取")
            return [], []

        texts = []
        metadatas = []
        ppt_files = sorted([f for f in os.listdir(PPT_DIR) if f.endswith(".pptx")])

        for ppt_file in ppt_files:
            ppt_path = os.path.join(PPT_DIR, ppt_file)
            try:
                prs = Presentation(ppt_path)
                chapter_name = ppt_file.replace(".pptx", "")
                full_text_parts = []
                for slide_num, slide in enumerate(prs.slides, 1):
                    slide_texts = []
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            for paragraph in shape.text_frame.paragraphs:
                                t = paragraph.text.strip()
                                if t:
                                    slide_texts.append(t)
                    if slide_texts:
                        full_text_parts.append(f"--- 幻灯片 {slide_num} ---\n" + "\n".join(slide_texts))

                full_text = "\n\n".join(full_text_parts)

                # 分块: 每 ~1500 字符一块，尊重段落边界
                chunks = self._chunk_text(full_text, max_chars=1500)
                for i, chunk in enumerate(chunks):
                    texts.append(chunk)
                    metadatas.append({
                        "text": chunk,
                        "source": "ppt",
                        "chapter": chapter_name,
                        "file": ppt_file,
                        "chunk_index": i,
                        "difficulty": self._infer_difficulty(chapter_name),
                    })

                print(f"[Indexer] PPT {ppt_file}: {len(full_text_parts)} 页, {len(chunks)} 个文本块")

            except Exception as e:
                print(f"[Indexer] 解析 PPT 失败 {ppt_file}: {e}")

        print(f"[Indexer] PPT 文本: {len(texts)} 个文本块 (共 {len(ppt_files)} 个文件)")
        return texts, metadatas

    @staticmethod
    def _chunk_text(text: str, max_chars: int = 1500) -> list[str]:
        """按段落边界分块，每块不超过 max_chars"""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 <= max_chars:
                current = current + "\n\n" + para if current else para
            else:
                if current:
                    chunks.append(current)
                # 如果单段超长，硬切
                while len(para) > max_chars:
                    chunks.append(para[:max_chars])
                    para = para[max_chars:]
                current = para
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _infer_difficulty(chapter_name: str) -> str:
        """根据章节名称推断难度"""
        for keyword, diff in [
            ("概述", "简单"), ("基础", "简单"), ("流程控制", "简单"),
            ("字符串", "简单"), ("组合数据", "简单"), ("函数", "中等"),
            ("文件", "中等"), ("面向对象", "中等"), ("异常", "中等"),
            ("计算生态", "进阶"), ("飞机大战", "进阶"),
        ]:
            if keyword in chapter_name:
                return diff
        return "中等"

    # ================================================================
    # 嵌入
    # ================================================================

    def embed_batch(self, texts: list[str], desc: str = "") -> list[list[float]]:
        """批量嵌入，纯离线，秒级完成"""
        if not self.embedder.is_ready():
            print("[Indexer] Embedder 未就绪，请先运行 offline_embedder.load()")
            return []

        total = len(texts)
        print(f"  [{desc}] 嵌入 {total} 条...")
        vectors = self.embedder.embed_documents(texts)
        print(f"  [{desc}] 完成: {len(vectors)} 条, {self.dim}维")
        return vectors

    # ================================================================
    # 主流程
    # ================================================================

    def build_all(self):
        """完整构建流程（离线 TF-IDF+SVD，无需 API）"""
        print("=" * 60)
        print("RAG 索引构建器 — FAISS (离线 TF-IDF+SVD 256维)")
        print("=" * 60)

        # 确保离线模型已加载
        if not self.embedder.is_ready():
            self.embedder.load()
        if not self.embedder.is_ready():
            print("[Indexer] 错误: 离线模型加载失败")
            print("  请检查 data/models/ 目录下的预训练模型文件")
            return

        # 1. 加载数据
        path_texts, path_metas = self.load_learning_paths()
        ex_texts, ex_metas = self.load_exercises()
        ppt_texts, ppt_metas = self.load_ppt_texts()

        all_texts = path_texts + ex_texts + ppt_texts
        if not all_texts:
            print("[Indexer] 无数据可索引，请检查 data/knowledge_base/ 目录")
            return

        # 2. 构建学习路径索引 (路径知识点 + PPT 教材内容)
        path_index_texts = path_texts + ppt_texts
        path_index_metas = path_metas + ppt_metas

        if path_index_texts:
            print(f"\n[Indexer] 嵌入学习路径索引 ({len(path_index_texts)} 条)...")
            path_vectors = self.embed_batch(path_index_texts, desc="学习路径")
            self.client.build_path_index(path_vectors, path_index_metas)
            print(f"[Indexer] 学习路径索引: {len(path_vectors)} 条, {self.dim}维")
        else:
            print("[Indexer] 学习路径索引为空，跳过")

        # 3. 构建习题索引
        if ex_texts:
            print(f"\n[Indexer] 嵌入习题索引 ({len(ex_texts)} 条)...")
            ex_vectors = self.embed_batch(ex_texts, desc="习题")
            self.client.build_exercise_index(ex_vectors, ex_metas)
            print(f"[Indexer] 习题索引: {len(ex_vectors)} 条, {self.dim}维")
        else:
            print("[Indexer] 习题索引为空，跳过")

        # 4. 持久化
        print("\n[Indexer] 保存索引...")
        self.client.save()

        print("=" * 60)
        path_count = self.client.path_index.ntotal if self.client.path_index else 0
        ex_count = self.client.exercise_index.ntotal if self.client.exercise_index else 0
        print(f"索引构建完成!")
        print(f"  学习路径+PPT: {path_count} 条")
        print(f"  习题:         {ex_count} 条")
        print(f"  存储路径:     {FAISS_INDEX_DIR}")
        print("=" * 60)


def main():
    indexer = Indexer()
    indexer.build_all()


if __name__ == "__main__":
    main()
