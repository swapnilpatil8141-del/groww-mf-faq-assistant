"""Generate text embeddings for the saved RAG chunks.

Input:  data/chunks/chunks.jsonl
Output: data/embeddings/embedding_manifest.json

The vectors themselves are passed to the vector-store stage and are not
duplicated into a second large JSON file. This module never scrapes URLs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.config import PROJECT_ROOT, load_config

LOGGER = logging.getLogger(__name__)
EXPECTED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _load_embedding_model(model_name: str):
    """Load SentenceTransformer lazily so tests do not need model downloads."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return SentenceTransformer(model_name)


def generate_embeddings(
    project_root: Path = PROJECT_ROOT,
    model: Any | None = None,
    batch_size: int = 32,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Embed each valid chunk and save an inspectable embedding manifest.

    Args:
        project_root: Project root containing data/chunks/chunks.jsonl.
        model: Optional injected model for tests; production loads the configured
            SentenceTransformer model.
        batch_size: Number of chunk texts encoded per model call.

    Returns:
        A list of records containing chunk ID, vector, and metadata, plus a
        manifest summary. The vector records are returned for the next phase.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    config = load_config()
    model_name = config.get("embedding", {}).get("model")
    if model_name != EXPECTED_MODEL:
        raise ValueError(
            f"Configured embedding model must be {EXPECTED_MODEL!r}; got {model_name!r}."
        )

    chunks_path = project_root / "data" / "chunks" / "chunks.jsonl"
    output_dir = project_root / "data" / "embeddings"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not chunks_path.is_file():
        raise FileNotFoundError(
            f"Chunks not found: {chunks_path}. Run `python -m app.chunker` first."
        )

    chunks: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for line_number, line in enumerate(chunks_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            chunk = json.loads(line)
            chunk_id = chunk.get("chunk_id")
            text = chunk.get("text")
            if not chunk_id or not isinstance(text, str) or not text.strip():
                raise ValueError("chunk_id and non-empty text are required")
            if chunk_id in seen_ids:
                raise ValueError(f"Duplicate chunk_id: {chunk_id}")
            if not chunk.get("source_id") or not chunk.get("source_url"):
                raise ValueError("source_id and source_url metadata are required")
            seen_ids.add(chunk_id)
            chunks.append(chunk)
        except Exception as exc:
            skipped.append(
                {"line": str(line_number), "reason": f"{type(exc).__name__}: {exc}"}
            )

    if not chunks:
        raise ValueError("No valid chunks were found; embeddings were not generated.")

    embedding_model = model if model is not None else _load_embedding_model(model_name)
    texts = [chunk["text"] for chunk in chunks]

    try:
        vectors = embedding_model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    except TypeError:
        # A small compatibility fallback for injected/mock models.
        vectors = embedding_model.encode(texts)

    if len(vectors) != len(chunks):
        raise ValueError(
            f"Embedding count mismatch: {len(vectors)} vectors for {len(chunks)} chunks."
        )

    # A stable, one-dimensional numeric vector is required for every chunk.
    try:
        import numpy as np
        try:
            vectors = np.asarray(vectors)
        except ValueError as exc:
            raise ValueError("Embedding vectors have inconsistent dimensions.") from exc
        if vectors.ndim != 2 or not np.issubdtype(vectors.dtype, np.number):
            raise ValueError("Embedding model must return a 2D numeric vector array.")
        if not np.isfinite(vectors).all():
            raise ValueError("Embedding model returned NaN or infinite values.")
    except ImportError:
        # Dimension consistency is also checked per record below.
        pass

    records: list[dict[str, Any]] = []
    manifest_records: list[dict[str, Any]] = []
    vector_dimension: int | None = None

    for chunk, vector in zip(chunks, vectors):
        vector_list = vector.tolist() if hasattr(vector, "tolist") else list(vector)
        if not vector_list:
            skipped.append(
                {"chunk_id": chunk["chunk_id"], "reason": "Model returned an empty vector."}
            )
            continue
        if vector_dimension is None:
            vector_dimension = len(vector_list)
        elif len(vector_list) != vector_dimension:
            raise ValueError("Embedding vectors have inconsistent dimensions.")

        vector_hash = hashlib.sha256(
            json.dumps(vector_list, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        metadata = {
            key: chunk.get(key)
            for key in (
                "source_id", "source_title", "source_url", "section_title",
                "section_index", "chunk_index", "fetched_at",
            )
        }
        records.append(
            {
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "embedding": vector_list,
                "metadata": metadata,
            }
        )
        manifest_records.append(
            {
                "chunk_id": chunk["chunk_id"],
                "embedding_model": model_name,
                "vector_dimension": len(vector_list),
                "vector_sha256": vector_hash,
                "status": "success",
            }
        )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": model_name,
        "normalized_embeddings": True,
        "batch_size": batch_size,
        "input_chunk_count": len(chunks),
        "embedded_count": len(records),
        "skipped_count": len(skipped),
        "vector_dimension": vector_dimension,
        "records": manifest_records,
        "skipped": skipped,
        "note": "Vectors are returned by this function for ChromaDB ingestion; this manifest stores IDs and checksums, not full vectors.",
    }

    manifest_path = output_dir / "embedding_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    LOGGER.info(
        "Embedding finished: %s vectors generated using %s.",
        len(records), model_name
    )
    return records, manifest


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    records, manifest = generate_embeddings()
    print(
        f"Embedding completed: {len(records)}/{manifest['input_chunk_count']} "
        f"chunks embedded."
    )
    print(f"Model: {manifest['embedding_model']}")
    print(f"Vector dimension: {manifest['vector_dimension']}")
    print(f"Manifest: {PROJECT_ROOT / 'data' / 'embeddings' / 'embedding_manifest.json'}")


if __name__ == "__main__":
    main()
