"""
ChromaDB vector store for doctor appointment knowledge base.

Uses local sentence-transformers embeddings (no API key needed).
ChromaDB runs embedded (no separate server required).

Collections:
  - doctor_profiles  : full profile + appointment context chunks
  - doctor_expertise : expertise / procedure specific chunks
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chromadb
from loguru import logger
from sentence_transformers import SentenceTransformer

from src.knowledge_base.config import get_settings

settings = get_settings()

COLLECTION_PROFILES = "doctor_profiles"
COLLECTION_EXPERTISE = "doctor_expertise"


class VectorStore:
    def __init__(self, persist_dir: str | None = None, model_name: str | None = None):
        self._persist_dir = persist_dir or settings.chroma_persist_dir
        Path(self._persist_dir).mkdir(parents=True, exist_ok=True)

        # chromadb 1.x: Settings moved; use keyword arg directly
        self._client = chromadb.PersistentClient(
            path=self._persist_dir,
        )

        model = model_name or settings.embedding_model
        logger.info(f"Loading embedding model: {model}")
        self._embedder = SentenceTransformer(model, device=settings.embedding_device)

        self._profiles = self._client.get_or_create_collection(
            COLLECTION_PROFILES,
            metadata={"hnsw:space": "cosine"},
        )
        self._expertise = self._client.get_or_create_collection(
            COLLECTION_EXPERTISE,
            metadata={"hnsw:space": "cosine"},
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.encode(texts, normalize_embeddings=True).tolist()

    def _collection_for(self, chunk_type: str):
        if chunk_type == "expertise":
            return self._expertise
        return self._profiles  # profile + appointment_context go to profiles collection

    def upsert_chunks(self, chunks: list[dict], batch_size: int = 64):
        """Embed and upsert text chunks into the appropriate collections."""
        # Group by collection
        by_col: dict[str, list[dict]] = {}
        for chunk in chunks:
            col_key = "expertise" if chunk["chunk_type"] == "expertise" else "profiles"
            by_col.setdefault(col_key, []).append(chunk)

        for col_key, col_chunks in by_col.items():
            collection = self._expertise if col_key == "expertise" else self._profiles
            logger.info(f"Upserting {len(col_chunks)} chunks → {col_key} collection")

            for i in range(0, len(col_chunks), batch_size):
                batch = col_chunks[i : i + batch_size]
                ids = [c["id"] for c in batch]
                texts = [c["text"] for c in batch]
                metadatas = [_sanitize_meta(c["metadata"]) for c in batch]
                embeddings = self._embed(texts)

                collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=texts,
                    metadatas=metadatas,
                )
                logger.info(f"  Batch {i//batch_size + 1}: {len(batch)} chunks done")

        logger.success(f"Vector store upsert complete. Total chunks: {len(chunks)}")

    def semantic_search(
        self,
        query: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """
        Semantic search across all collections.
        Returns ranked list of { id, text, metadata, distance }.
        """
        query_embedding = self._embed([query])[0]
        all_results: list[dict] = []

        for collection in [self._profiles, self._expertise]:
            kwargs: dict[str, Any] = {
                "query_embeddings": [query_embedding],
                "n_results": n_results,
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                kwargs["where"] = where

            try:
                res = collection.query(**kwargs)
                for doc, meta, dist, rid in zip(
                    res["documents"][0],
                    res["metadatas"][0],
                    res["distances"][0],
                    res["ids"][0],
                ):
                    all_results.append({
                        "id": rid,
                        "text": doc,
                        "metadata": meta,
                        "score": 1 - dist,  # cosine similarity
                    })
            except Exception as e:
                logger.warning(f"Collection query error: {e}")

        # Sort by score descending, deduplicate by doctor_id
        all_results.sort(key=lambda x: x["score"], reverse=True)
        seen_doctors: set[str] = set()
        deduped: list[dict] = []
        for r in all_results:
            did = r["metadata"].get("doctor_id", r["id"])
            if did not in seen_doctors:
                seen_doctors.add(did)
                deduped.append(r)
        return deduped[:n_results]

    def search_by_doctor_id(self, doctor_id: str) -> list[dict]:
        """Fetch all chunks for a specific doctor."""
        results = self._profiles.get(
            where={"doctor_id": {"$eq": doctor_id}},
            include=["documents", "metadatas"],
        )
        chunks = []
        for doc, meta, rid in zip(results["documents"], results["metadatas"], results["ids"]):
            chunks.append({"id": rid, "text": doc, "metadata": meta})
        return chunks

    def load_from_file(self, chunks_path: str | None = None):
        """Load chunks.json and upsert into ChromaDB."""
        path = Path(chunks_path or settings.processed_data_dir) / "chunks.json"
        chunks = json.loads(path.read_text(encoding="utf-8"))
        logger.info(f"Loading {len(chunks)} chunks from {path}")
        self.upsert_chunks(chunks)


def _sanitize_meta(meta: dict) -> dict:
    """ChromaDB metadata values must be str/int/float/bool."""
    clean = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            clean[k] = v
        elif isinstance(v, list):
            clean[k] = ", ".join(str(i) for i in v)
        elif v is None:
            clean[k] = ""
        else:
            clean[k] = str(v)
    return clean


if __name__ == "__main__":
    store = VectorStore()
    store.load_from_file()
