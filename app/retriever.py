
"""Retrieve the most relevant approved-source chunks from ChromaDB.

The query embedding uses the exact configured ingestion model. Retrieval
traces intentionally omit the raw user question; they store a query hash,
a generated trace ID, and returned evidence metadata only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, load_config

LOGGER = logging.getLogger(__name__)


def _load_chromadb():
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError(
            "chromadb is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return chromadb


def _load_embedding_model(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return SentenceTransformer(model_name)


def _make_query_embedding(model: Any, question: str) -> list[float]:
    try:
        encoded = model.encode(
            [question],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except TypeError:
        # Compatibility for small injected test models.
        encoded = model.encode([question])

    if len(encoded) != 1:
        raise ValueError("The embedding model must return exactly one query vector.")

    vector = encoded[0]
    vector = vector.tolist() if hasattr(vector, "tolist") else list(vector)

    if not vector:
        raise ValueError("The embedding model returned an empty query vector.")

    try:
        vector = [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise ValueError("The query embedding contains non-numeric values.") from exc

    if any(not math.isfinite(value) for value in vector):
        raise ValueError("The query embedding contains non-finite values.")

    return vector


def _write_trace(project_root: Path, trace: dict[str, Any]) -> Path:
    trace_path = project_root / "data" / "retrieval" / "retrieval_traces.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, ensure_ascii=False) + "\n")

    return trace_path


def retrieve(
    question: str,
    project_root: Path = PROJECT_ROOT,
    model: Any | None = None,
    client: Any | None = None,
    trace_id: str | None = None,
    source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Embed a question, query ChromaDB, and persist a privacy-safe trace.

    Args:
        question: Factual question from the user.
        project_root: Project root containing config and persisted data.
        model/client: Optional injected dependencies for deterministic tests.
        trace_id: Optional caller-provided test/request ID.
        source_ids: Optional list of source IDs to restrict retrieval to.

    Returns:
        A result with status, query ID/hash, top results, and trace file path.
        Raw question text is not included in the return trace or persisted log.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("A non-empty question is required.")

    config = load_config()
    embedding_config = config.get("embedding", {})
    vector_config = config.get("vector_db", {})
    retrieval_config = config.get("retrieval", {})

    model_name = embedding_config.get("model")
    if not model_name:
        raise ValueError("embedding.model is required.")

    top_k = retrieval_config.get("top_k", 4)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("retrieval.top_k must be a positive integer.")

    provider = vector_config.get("provider")
    collection_name = vector_config.get("collection_name")
    persist_value = vector_config.get("persist_directory")

    if provider != "chroma" or not collection_name or not persist_value:
        raise ValueError("A valid ChromaDB provider, collection, and path are required.")

    embedding_model = (
        model if model is not None else _load_embedding_model(model_name)
    )
    query_vector = _make_query_embedding(
        embedding_model,
        question.strip(),
    )

    persist_path = Path(persist_value)
    if not persist_path.is_absolute():
        persist_path = project_root / persist_path

    if client is None:
        chromadb = _load_chromadb()
        client = chromadb.PersistentClient(path=str(persist_path))

    try:
        collection = client.get_collection(name=collection_name)
    except Exception as exc:
        raise RuntimeError(
            f"ChromaDB collection {collection_name!r} was not found. "
            "Complete Phase 6 before running retrieval."
        ) from exc

    collection_metadata = collection.metadata or {}
    stored_model = collection_metadata.get("embedding_model")

    if stored_model != model_name:
        raise ValueError(
            "Query embedding model does not match the ChromaDB collection. "
            f"configured={model_name!r}, stored={stored_model!r}."
        )

    # Apply an optional scheme-specific source filter.
    where_filter = None

    if source_ids:
        where_filter = {
            "source_id": {"$in": source_ids}
        }

    # Use the total collection count for compatibility with ChromaDB
    # versions that do not support count(where=...).
    total_count = collection.count()

    if total_count == 0:
        raw_results = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
    else:
        query_args = {
            "query_embeddings": [query_vector],
            "n_results": min(top_k, total_count),
            "include": ["documents", "metadatas", "distances"],
        }

        # ChromaDB applies the scheme filter during the vector query.
        if where_filter:
            query_args["where"] = where_filter

        raw_results = collection.query(**query_args)

    ids = (raw_results.get("ids") or [[]])[0] or []
    documents = (raw_results.get("documents") or [[]])[0] or []
    metadatas = (raw_results.get("metadatas") or [[]])[0] or []
    distances = (raw_results.get("distances") or [[]])[0] or []

    threshold = retrieval_config.get("relevance_threshold")

    if threshold is not None:
        try:
            threshold = float(threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "retrieval.relevance_threshold must be numeric or null."
            ) from exc

        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError(
                "retrieval.relevance_threshold must be a finite non-negative distance."
            )

    results: list[dict[str, Any]] = []

    for index, chunk_id in enumerate(ids):
        document = documents[index] if index < len(documents) else None
        metadata = metadatas[index] if index < len(metadatas) else None
        distance = distances[index] if index < len(distances) else None

        if not chunk_id or not isinstance(document, str) or not document.strip():
            continue

        if not isinstance(metadata, dict):
            metadata = {}

        if threshold is not None and (
            distance is None or float(distance) > threshold
        ):
            continue

        numeric_distance = float(distance) if distance is not None else None

        results.append(
            {
                "chunk_id": str(chunk_id),
                "text": document,
                "source_id": metadata.get("source_id"),
                "source_url": metadata.get("source_url"),
                "scheme_name": metadata.get("source_title"),
                "section_title": metadata.get("section_title"),
                "fetched_at": metadata.get("fetched_at"),
                "distance": numeric_distance,
                # Chroma's configured metric is cosine distance; similarity is
                # a convenient monotonic display value, not a calibrated probability.
                "score": (
                    1.0 - numeric_distance
                    if numeric_distance is not None
                    else None
                ),
            }
        )

    generated_trace_id = trace_id or str(uuid.uuid4())
    query_hash = hashlib.sha256(
        question.strip().encode("utf-8")
    ).hexdigest()

    status = "ok" if results else "no_evidence"

    trace = {
        "trace_id": generated_trace_id,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "query_sha256": query_hash,
        "status": status,
        "embedding_model": model_name,
        "collection_name": collection_name,
        "top_k": top_k,
        "relevance_threshold": threshold,
        "result_count": len(results),
        "results": [
            {
                "chunk_id": item["chunk_id"],
                "source_id": item["source_id"],
                "source_url": item["source_url"],
                "scheme_name": item["scheme_name"],
                "distance": item["distance"],
                "score": item["score"],
            }
            for item in results
        ],
        # Deliberately no raw question or user-supplied text in the trace.
    }

    trace_path = _write_trace(project_root, trace)

    response = {
        "status": status,
        "trace_id": generated_trace_id,
        "query_sha256": query_hash,
        "collection_name": collection_name,
        "embedding_model": model_name,
        "top_k": top_k,
        "result_count": len(results),
        "results": results,
        "trace_path": str(trace_path),
    }

    LOGGER.info(
        "Retrieval %s: %s result(s) from collection '%s' (trace=%s).",
        status,
        len(results),
        collection_name,
        generated_trace_id,
    )

    return response


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retrieve evidence from the Groww FAQ vector database."
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="A factual question to search.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    question = args.question
    if not question:
        question = input("Enter a factual question: ").strip()

    result = retrieve(question)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["status"] == "no_evidence":
        print(
            "\nCannot verify: no relevant evidence was returned "
            "from the configured source collection."
        )


if __name__ == "__main__":
    main()
