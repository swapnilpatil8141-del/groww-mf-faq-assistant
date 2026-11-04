import json
from pathlib import Path

import pytest

from app.vector_store import inspect_collection, store_embeddings


class FakeCollection:
    def __init__(self, name, metadata):
        self.name = name
        self.metadata = metadata
        self.records = {}

    def count(self):
        return len(self.records)

    def upsert(self, ids, documents, embeddings, metadatas):
        for chunk_id, document, embedding, metadata in zip(ids, documents, embeddings, metadatas):
            self.records[chunk_id] = {
                "document": document, "embedding": embedding, "metadata": metadata
            }

    def get(self, ids=None, include=None):
        selected = list(self.records) if ids is None else [x for x in ids if x in self.records]
        return {
            "ids": selected,
            "documents": [self.records[x]["document"] for x in selected],
            "metadatas": [self.records[x]["metadata"] for x in selected],
        }


class FakeClient:
    def __init__(self, metadata=None):
        self.collection = None
        self.metadata = metadata

    def get_or_create_collection(self, name, metadata):
        if self.collection is None:
            self.collection = FakeCollection(name, self.metadata if self.metadata is not None else metadata)
        return self.collection

    def get_collection(self, name):
        if self.collection is None:
            raise KeyError(name)
        return self.collection


def make_record(chunk_id="hdfc_large_cap_0000", source_id="hdfc_large_cap"):
    return {
        "chunk_id": chunk_id,
        "text": "Expense ratio is listed in the scheme details.",
        "embedding": [0.1, 0.2, 0.3],
        "metadata": {
            "source_id": source_id,
            "source_title": "HDFC Large Cap Fund",
            "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
            "section_title": "Scheme Details",
            "section_index": 0,
            "chunk_index": 0,
            "fetched_at": "2026-11-02T10:00:00+00:00",
        },
    }


def test_upserts_vectors_and_persists_inspectable_manifest(tmp_path):
    client = FakeClient()
    records = [make_record(), make_record("hdfc_large_cap_0001")]
    manifest = {"embedding_model": "sentence-transformers/all-MiniLM-L6-v2"}

    result = store_embeddings(tmp_path, records, manifest, client=client)

    assert result["upserted_count"] == 2
    assert result["collection_count"] == 2
    assert result["vector_dimension"] == 3
    assert result["source_counts"] == {"hdfc_large_cap": 2}
    saved = json.loads(
        (tmp_path / "data/embeddings/vector_store_manifest.json").read_text()
    )
    assert saved["status"] == "success"
    assert client.collection.records["hdfc_large_cap_0000"]["metadata"]["embedding_model"] == manifest["embedding_model"]
    assert client.collection.records["hdfc_large_cap_0000"]["metadata"]["source_url"] == records[0]["metadata"]["source_url"]


def test_rerunning_upsert_does_not_duplicate_ids(tmp_path):
    client = FakeClient()
    records = [make_record()]
    manifest = {"embedding_model": "sentence-transformers/all-MiniLM-L6-v2"}

    store_embeddings(tmp_path, records, manifest, client=client)
    store_embeddings(tmp_path, records, manifest, client=client)

    assert client.collection.count() == 1


def test_rejects_embedding_model_mismatch(tmp_path):
    client = FakeClient(metadata={"embedding_model": "some/other-model"})
    with pytest.raises(ValueError, match="Embedding model mismatch"):
        store_embeddings(
            tmp_path,
            [make_record()],
            {"embedding_model": "sentence-transformers/all-MiniLM-L6-v2"},
            client=client,
        )


def test_rejects_nonempty_collection_without_model_metadata(tmp_path):
    client = FakeClient(metadata={})
    client.collection = FakeCollection("hdfc_mutual_fund_faq", {})
    client.collection.records["existing"] = {"document": "x"}
    with pytest.raises(ValueError, match="no embedding_model metadata"):
        store_embeddings(
            tmp_path,
            [make_record()],
            {"embedding_model": "sentence-transformers/all-MiniLM-L6-v2"},
            client=client,
        )


def test_rejects_duplicate_chunk_ids(tmp_path):
    with pytest.raises(ValueError, match="Duplicate chunk_id"):
        store_embeddings(
            tmp_path,
            [make_record(), make_record()],
            {"embedding_model": "sentence-transformers/all-MiniLM-L6-v2"},
            client=FakeClient(),
        )


def test_rejects_inconsistent_vector_dimensions(tmp_path):
    second = make_record("hdfc_large_cap_0001")
    second["embedding"] = [0.1, 0.2]
    with pytest.raises(ValueError, match="inconsistent vector dimensions"):
        store_embeddings(
            tmp_path,
            [make_record(), second],
            {"embedding_model": "sentence-transformers/all-MiniLM-L6-v2"},
            client=FakeClient(),
        )


def test_inspect_collection_returns_count_and_metadata(tmp_path):
    client = FakeClient()
    store_embeddings(
        tmp_path,
        [make_record()],
        {"embedding_model": "sentence-transformers/all-MiniLM-L6-v2"},
        client=client,
    )
    result = inspect_collection(tmp_path, client=client)
    assert result["count"] == 1
    assert result["collection_name"] == "hdfc_mutual_fund_faq"
