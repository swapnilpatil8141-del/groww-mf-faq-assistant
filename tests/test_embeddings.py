import json
from pathlib import Path

import pytest

from app.embeddings import EXPECTED_MODEL, generate_embeddings


class FakeEmbeddingModel:
    def __init__(self, dimension=4):
        self.dimension = dimension
        self.received_texts = None
        self.kwargs = None

    def encode(self, texts, **kwargs):
        self.received_texts = list(texts)
        self.kwargs = kwargs
        return [
            [float(index + 1)] * self.dimension
            for index, _ in enumerate(texts)
        ]


def write_chunks(tmp_path, chunks):
    path = tmp_path / "data/chunks/chunks.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(chunk) + "\n" for chunk in chunks),
        encoding="utf-8",
    )


def make_chunk(chunk_id="hdfc_large_cap_0000"):
    return {
        "chunk_id": chunk_id,
        "source_id": "hdfc_large_cap",
        "source_title": "HDFC Large Cap Fund",
        "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "section_title": "Scheme Details",
        "section_index": 0,
        "chunk_index": 0,
        "fetched_at": "2026-11-02T10:00:00+00:00",
        "text": "Scheme Details. Expense ratio is 0.50%.",
    }


def test_generates_vector_for_each_chunk_and_saves_manifest(tmp_path):
    write_chunks(tmp_path, [make_chunk(), make_chunk("hdfc_large_cap_0001")])
    fake_model = FakeEmbeddingModel()
    records, manifest = generate_embeddings(tmp_path, model=fake_model)

    assert len(records) == 2
    assert manifest["embedded_count"] == 2
    assert manifest["embedding_model"] == EXPECTED_MODEL
    assert manifest["vector_dimension"] == 4
    assert records[0]["chunk_id"] == "hdfc_large_cap_0000"
    assert len(records[0]["embedding"]) == 4
    assert fake_model.kwargs["normalize_embeddings"] is True

    saved = json.loads(
        (tmp_path / "data/embeddings/embedding_manifest.json").read_text()
    )
    assert saved["embedded_count"] == 2
    assert saved["records"][0]["status"] == "success"


def test_chunk_id_and_metadata_are_preserved(tmp_path):
    write_chunks(tmp_path, [make_chunk()])
    records, _ = generate_embeddings(tmp_path, model=FakeEmbeddingModel())
    assert records[0]["metadata"]["source_id"] == "hdfc_large_cap"
    assert records[0]["metadata"]["source_url"] == make_chunk()["source_url"]
    assert records[0]["text"] == make_chunk()["text"]


def test_missing_chunks_file_raises_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run `python -m app.chunker` first"):
        generate_embeddings(tmp_path, model=FakeEmbeddingModel())


def test_empty_chunks_file_is_rejected(tmp_path):
    path = tmp_path / "data/chunks/chunks.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="No valid chunks"):
        generate_embeddings(tmp_path, model=FakeEmbeddingModel())


def test_duplicate_chunk_ids_are_not_embedded_twice(tmp_path):
    chunk = make_chunk()
    write_chunks(tmp_path, [chunk, chunk])
    records, manifest = generate_embeddings(tmp_path, model=FakeEmbeddingModel())
    assert len(records) == 1
    assert manifest["skipped_count"] == 1
    assert "Duplicate chunk_id" in manifest["skipped"][0]["reason"]


def test_invalid_chunk_record_is_skipped(tmp_path):
    valid = make_chunk()
    invalid = {"chunk_id": "bad", "text": " "}
    write_chunks(tmp_path, [valid, invalid])
    records, manifest = generate_embeddings(tmp_path, model=FakeEmbeddingModel())
    assert len(records) == 1
    assert manifest["skipped_count"] == 1


def test_batch_size_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="batch_size"):
        generate_embeddings(tmp_path, model=FakeEmbeddingModel(), batch_size=0)


class BadDimensionModel:
    def encode(self, texts, **kwargs):
        return [[0.1, 0.2], [0.1, 0.2, 0.3]]


def test_inconsistent_vector_dimensions_are_rejected(tmp_path):
    write_chunks(tmp_path, [make_chunk(), make_chunk("hdfc_large_cap_0001")])
    with pytest.raises(ValueError, match="inconsistent dimensions"):
        generate_embeddings(tmp_path, model=BadDimensionModel())
