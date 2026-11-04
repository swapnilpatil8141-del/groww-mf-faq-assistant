"""Persist embedded chunks in a ChromaDB collection.

Input:  data/chunks/chunks.jsonl + data/embeddings/embedding_manifest.json
Output: persistent ChromaDB collection under the configured data directory,
        plus data/embeddings/vector_store_manifest.json.

The stage reuses Phase 5's embedding function so ingestion and query-time
embedding remain tied to the same configured model.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, load_config
from app.embeddings import generate_embeddings

LOGGER = logging.getLogger(__name__)
COLLECTION_SCHEMA_VERSION = "1"


def _load_chromadb():
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError(
            "chromadb is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return chromadb


def _chroma_metadata(metadata: dict[str, Any], embedding_model: str) -> dict[str, Any]:
    """Convert source metadata to Chroma-supported scalar values."""
    result: dict[str, Any] = {"embedding_model": embedding_model}
    for key in (
        "source_id", "source_title", "source_url", "section_title",
        "section_index", "chunk_index", "fetched_at",
    ):
        value = metadata.get(key)
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
        else:
            result[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    required = ("source_id", "source_url", "fetched_at")
    missing = [key for key in required if not result.get(key)]
    if missing:
        raise ValueError(
            f"Chunk metadata is missing required field(s): {', '.join(missing)}"
        )
    return result


def _get_or_create_collection(client: Any, collection_name: str, model_name: str):
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={
            "embedding_model": model_name,
            "hnsw:space": "cosine",
            "schema_version": COLLECTION_SCHEMA_VERSION,
        },
    )
    existing_metadata = collection.metadata or {}
    existing_model = existing_metadata.get("embedding_model")
    if existing_model and existing_model != model_name:
        raise ValueError(
            "Embedding model mismatch for the existing ChromaDB collection: "
            f"stored={existing_model!r}, configured={model_name!r}. "
            "Use a new collection or rebuild it; do not mix vector spaces."
        )
    if existing_model is None:
        # A pre-existing unlabelled collection is unsafe to reuse because its
        # vector space cannot be verified.
        if collection.count() > 0:
            raise ValueError(
                "The configured ChromaDB collection already contains records "
                "but has no embedding_model metadata. Use a new collection or "
                "rebuild it to prevent mixing incompatible vectors."
            )
    return collection


def store_embeddings(
    project_root: Path = PROJECT_ROOT,
    records: list[dict[str, Any]] | None = None,
    manifest: dict[str, Any] | None = None,
    client: Any | None = None,
    batch_size: int = 100,
) -> dict[str, Any]:
    """Upsert embedded chunks into persistent ChromaDB and save an audit manifest.

    Optional records/client parameters make the function testable without
    downloading the embedding model or opening a real ChromaDB database.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    config = load_config()
    vector_config = config.get("vector_db", {})
    if vector_config.get("provider") != "chroma":
        raise ValueError("vector_db.provider must be 'chroma'.")

    persist_value = vector_config.get("persist_directory")
    collection_name = vector_config.get("collection_name")
    if not persist_value or not collection_name:
        raise ValueError(
            "Configure vector_db.persist_directory and vector_db.collection_name."
        )

    model_name = config.get("embedding", {}).get("model")
    if not model_name:
        raise ValueError("embedding.model is required.")

    if records is None or manifest is None:
        records, manifest = generate_embeddings(project_root=project_root)

    if manifest.get("embedding_model") != model_name:
        raise ValueError(
            "Embedding manifest model does not match config/config.yaml. "
            "Regenerate embeddings before storing."
        )
    if not records:
        raise ValueError("No embedding records were supplied; nothing to store.")

    persist_path = Path(persist_value)
    if not persist_path.is_absolute():
        persist_path = project_root / persist_path
    persist_path.mkdir(parents=True, exist_ok=True)

    if client is None:
        chromadb = _load_chromadb()
        client = chromadb.PersistentClient(path=str(persist_path))

    collection = _get_or_create_collection(client, collection_name, model_name)

    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    dimensions: set[int] = set()
    source_counts: Counter[str] = Counter()

    for record in records:
        chunk_id = record.get("chunk_id")
        text = record.get("text")
        vector = record.get("embedding")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError("Every vector record must have a non-empty chunk_id.")
        if chunk_id in seen_ids:
            raise ValueError(f"Duplicate chunk_id in embedding records: {chunk_id}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Chunk {chunk_id} has empty text.")
        if not isinstance(vector, (list, tuple)) or not vector:
            raise ValueError(f"Chunk {chunk_id} has no embedding vector.")
        try:
            vector_values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Chunk {chunk_id} has a non-numeric vector.") from exc
        if any(not __import__("math").isfinite(value) for value in vector_values):
            raise ValueError(f"Chunk {chunk_id} has a non-finite vector value.")
        dimensions.add(len(vector_values))
        metadata = _chroma_metadata(record.get("metadata") or {}, model_name)

        seen_ids.add(chunk_id)
        ids.append(chunk_id)
        documents.append(text)
        embeddings.append(vector_values)
        metadatas.append(metadata)
        source_counts[str(metadata["source_id"])] += 1

    if len(dimensions) != 1:
        raise ValueError("Embedding records have inconsistent vector dimensions.")
    vector_dimension = next(iter(dimensions))

    # Chroma upsert is idempotent for stable chunk IDs: reruns update records
    # rather than appending duplicate rows.
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        collection.upsert(
            ids=ids[start:end],
            documents=documents[start:end],
            embeddings=embeddings[start:end],
            metadatas=metadatas[start:end],
        )

    stored_count = collection.count()
    stored = collection.get(
        ids=ids[: min(5, len(ids))],
        include=["metadatas", "documents"],
    )
    stored_ids = set(stored.get("ids") or [])
    if not set(ids[: min(5, len(ids))]).issubset(stored_ids):
        raise RuntimeError("ChromaDB verification failed for sample upserted IDs.")

    result = {
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "provider": "chroma",
        "persist_directory": str(persist_path.resolve()),
        "collection_name": collection_name,
        "embedding_model": model_name,
        "vector_dimension": vector_dimension,
        "upserted_count": len(ids),
        "collection_count": stored_count,
        "source_counts": dict(sorted(source_counts.items())),
        "sample_chunk_ids_verified": sorted(stored_ids),
        "chunk_ids": ids,
        "status": "success",
    }

    manifest_path = project_root / "data" / "embeddings" / "vector_store_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    LOGGER.info(
        "Stored %s vectors in ChromaDB collection '%s' (total=%s).",
        len(ids), collection_name, stored_count,
    )
    return result


def inspect_collection(project_root: Path = PROJECT_ROOT, client: Any | None = None) -> dict[str, Any]:
    """Return inspectable collection metadata and count without embedding."""
    config = load_config()
    vector_config = config["vector_db"]
    persist_path = Path(vector_config["persist_directory"])
    if not persist_path.is_absolute():
        persist_path = project_root / persist_path
    if client is None:
        chromadb = _load_chromadb()
        client = chromadb.PersistentClient(path=str(persist_path))
    try:
        collection = client.get_collection(name=vector_config["collection_name"])
    except Exception as exc:
        raise RuntimeError(
            f"ChromaDB collection {vector_config['collection_name']!r} was not found. "
            "Run `python -m app.vector_store` first."
        ) from exc
    return {
        "collection_name": collection.name,
        "count": collection.count(),
        "metadata": collection.metadata or {},
        "persist_directory": str(persist_path.resolve()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Store or inspect the FAQ vector collection.")
    parser.add_argument("--inspect", action="store_true", help="Inspect the configured collection.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.inspect:
        result = inspect_collection()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    result = store_embeddings()
    print(f"ChromaDB upsert completed: {result['upserted_count']} records.")
    print(f"Collection: {result['collection_name']}")
    print(f"Collection count: {result['collection_count']}")
    print(f"Embedding model: {result['embedding_model']}")
    print(f"Vector dimension: {result['vector_dimension']}")
    print(f"Manifest: {PROJECT_ROOT / 'data' / 'embeddings' / 'vector_store_manifest.json'}")


if __name__ == "__main__":
    main()
