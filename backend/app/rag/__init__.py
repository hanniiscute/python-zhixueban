"""RAG 层 — 基于 FAISS 的向量检索"""

from app.rag.embedder import spark_embedder
from app.rag.faiss_client import faiss_client
from app.rag.retriever import retriever

__all__ = ["spark_embedder", "faiss_client", "retriever"]
