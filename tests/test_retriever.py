import json
from pathlib import Path

import pytest

import app.retriever as retriever


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class FakeEmbeddingModel:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        return [[0.11, 0.22, 0.33]]


class FakeCollection:
    name = "hdfc_mutual_fund_faq"

    def __init__(self, records=None, metadata=None):
        self.records = records or []
        self.metadata = metadata or {"embedding_model": MODEL_NAME}
        self.query_args = None

    def count(self):
        return len(self.records)

    def query(self, query_embeddings, n_results, include):
        self.query_args = {
            "query_embeddings": query_embeddings,
            "n_results": n_results,
            "include": include,
        }
        rows = self.records[:n_results]
        return {
            "ids": [[row["chunk_id"] for row in rows]],
            "documents": [[row["text"] for row in rows]],
            "metadatas": [[row["metadata"] for row in rows]],
            "distances": [[row["distance"] for row in rows]],
        }


class FakeClient:
    def __init__(self, collection):
        self.collection = collection
        self.requested_name = None

    def get_collection(self, name):
        self.requested_name = name
        return self.collection


def test_retrieves_top_k_with_source_metadata_and_score(tmp_path, monkeypatch):
    collection = FakeCollection([
        {
            "chunk_id": "hdfc_large_cap_0001",
            "text": "The scheme's expense ratio information.",
            "metadata": {
                "source_id": "hdfc_large_cap",
                "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
                "source_title": "HDFC Large Cap Fund Direct Growth",
                "section_title": "Scheme Details",
                "fetched_at": "2026-11-02T10:00:00+00:00",
            },
            "distance": 0.12,
        },
        {
            "chunk_id": "hdfc_large_cap_0002",
            "text": "Additional scheme detail.",
            "metadata": {
                "source_id": "hdfc_large_cap",
                "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
                "source_title": "HDFC Large Cap Fund Direct Growth",
                "section_title": "Other Details",
                "fetched_at": "2026-11-02T10:00:00+00:00",
            },
            "distance": 0.25,
        },
    ])
    client = FakeClient(collection)
    model = FakeEmbeddingModel()
    monkeypatch.setattr(retriever, "load_config", lambda: {
        "embedding": {"model": MODEL_NAME},
        "vector_db": {
            "provider": "chroma",
            "persist_directory": "./data/chroma",
            "collection_name": "hdfc_mutual_fund_faq",
        },
        "retrieval": {"top_k": 2, "relevance_threshold": None},
    })

    result = retriever.retrieve(
        "What is the expense ratio of HDFC Large Cap Fund?",
        project_root=tmp_path,
        model=model,
        client=client,
        trace_id="test-retrieval-001",
    )

    assert result["status"] == "ok"
    assert result["result_count"] == 2
    assert result["results"][0]["chunk_id"] == "hdfc_large_cap_0001"
    assert result["results"][0]["source_url"].startswith("https://groww.in/")
    assert result["results"][0]["scheme_name"] == "HDFC Large Cap Fund Direct Growth"
    assert result["results"][0]["distance"] == 0.12
    assert result["results"][0]["score"] == pytest.approx(0.88)
    assert model.calls[0][0] == ["What is the expense ratio of HDFC Large Cap Fund?"]
    assert model.calls[0][1]["normalize_embeddings"] is True
    assert client.requested_name == "hdfc_mutual_fund_faq"
    assert collection.query_args["n_results"] == 2


def test_query_trace_does_not_store_raw_question_or_pii(tmp_path, monkeypatch):
    secret_question = "What is the fund detail? Email swapnil@example.com and phone 9876543210"
    collection = FakeCollection([])
    monkeypatch.setattr(retriever, "load_config", lambda: {
        "embedding": {"model": MODEL_NAME},
        "vector_db": {
            "provider": "chroma",
            "persist_directory": "./data/chroma",
            "collection_name": "hdfc_mutual_fund_faq",
        },
        "retrieval": {"top_k": 4},
    })

    result = retriever.retrieve(
        secret_question,
        project_root=tmp_path,
        model=FakeEmbeddingModel(),
        client=FakeClient(collection),
        trace_id="privacy-test",
    )

    trace_text = (tmp_path / "data/retrieval/retrieval_traces.jsonl").read_text()
    assert result["status"] == "no_evidence"
    assert secret_question not in trace_text
    assert "swapnil@example.com" not in trace_text
    assert "9876543210" not in trace_text
    trace = json.loads(trace_text)
    assert trace["trace_id"] == "privacy-test"
    assert trace["query_sha256"] == result["query_sha256"]


def test_returns_no_evidence_when_collection_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(retriever, "load_config", lambda: {
        "embedding": {"model": MODEL_NAME},
        "vector_db": {
            "provider": "chroma",
            "persist_directory": "./data/chroma",
            "collection_name": "hdfc_mutual_fund_faq",
        },
        "retrieval": {"top_k": 4},
    })
    result = retriever.retrieve(
        "What is the exit load?",
        project_root=tmp_path,
        model=FakeEmbeddingModel(),
        client=FakeClient(FakeCollection([])),
    )
    assert result["status"] == "no_evidence"
    assert result["results"] == []


def test_relevance_threshold_filters_far_results(tmp_path, monkeypatch):
    collection = FakeCollection([
        {
            "chunk_id": "chunk-far",
            "text": "Unrelated content.",
            "metadata": {"source_id": "hdfc_amc_overview", "source_url": "https://groww.in/mutual-funds/amc/hdfc-mutual-funds", "source_title": "HDFC AMC"},
            "distance": 0.9,
        }
    ])
    monkeypatch.setattr(retriever, "load_config", lambda: {
        "embedding": {"model": MODEL_NAME},
        "vector_db": {
            "provider": "chroma",
            "persist_directory": "./data/chroma",
            "collection_name": "hdfc_mutual_fund_faq",
        },
        "retrieval": {"top_k": 4, "relevance_threshold": 0.5},
    })
    result = retriever.retrieve(
        "Question with no close evidence",
        project_root=tmp_path,
        model=FakeEmbeddingModel(),
        client=FakeClient(collection),
    )
    assert result["status"] == "no_evidence"
    assert result["result_count"] == 0


def test_rejects_collection_with_different_embedding_model(tmp_path, monkeypatch):
    collection = FakeCollection([], metadata={"embedding_model": "another/model"})
    monkeypatch.setattr(retriever, "load_config", lambda: {
        "embedding": {"model": MODEL_NAME},
        "vector_db": {
            "provider": "chroma",
            "persist_directory": "./data/chroma",
            "collection_name": "hdfc_mutual_fund_faq",
        },
        "retrieval": {"top_k": 4},
    })
    with pytest.raises(ValueError, match="does not match"):
        retriever.retrieve(
            "What is the expense ratio?",
            project_root=tmp_path,
            model=FakeEmbeddingModel(),
            client=FakeClient(collection),
        )


def test_rejects_invalid_top_k(tmp_path, monkeypatch):
    monkeypatch.setattr(retriever, "load_config", lambda: {
        "embedding": {"model": MODEL_NAME},
        "vector_db": {
            "provider": "chroma",
            "persist_directory": "./data/chroma",
            "collection_name": "hdfc_mutual_fund_faq",
        },
        "retrieval": {"top_k": 0},
    })
    with pytest.raises(ValueError, match="positive integer"):
        retriever.retrieve(
            "What is the expense ratio?",
            project_root=tmp_path,
            model=FakeEmbeddingModel(),
            client=FakeClient(FakeCollection([])),
        )


def test_requires_nonempty_question():
    with pytest.raises(ValueError, match="non-empty"):
        retriever.retrieve("   ")
