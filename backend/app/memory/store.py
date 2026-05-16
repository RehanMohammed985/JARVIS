from __future__ import annotations

import uuid
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

from app.config import settings


class MemoryStore:
    def __init__(self) -> None:
        settings.chroma_path.mkdir(parents=True, exist_ok=True)
        self._ef = OllamaEmbeddingFunction(
            url=settings.ollama_base_url,
            model_name="nomic-embed-text",
        )
        self._client = chromadb.PersistentClient(
            path=str(settings.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=settings.memory_collection,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

    def remember(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        doc_id = str(uuid.uuid4())
        self._collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
        return doc_id

    def recall(self, query: str, k: int = 6) -> list[str]:
        res = self._collection.query(
            query_texts=[query],
            n_results=k,
        )
        docs = res.get("documents") or [[]]
        return docs[0] if docs else []


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
