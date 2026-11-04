import json
from pathlib import Path

import pytest

from app.chunker import _split_long_block, chunk_parsed_documents


def write_parsed(tmp_path, docs):
    path = tmp_path / "data/parsed/parsed_documents.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(doc) + "\n" for doc in docs), encoding="utf-8")


def base_doc(source_id="hdfc_large_cap", sections=None):
    return {
        "metadata": {
            "source_id": source_id,
            "source_title": "HDFC Large Cap Fund",
            "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
            "fetched_at": "2026-11-02T10:00:00+00:00",
        },
        "sections": sections or [
            {
                "section_title": "Scheme Details",
                "blocks": ["Expense ratio | 0.50%", "Minimum SIP | Rs 100", "Exit load | 1%"],
            }
        ],
    }


def test_chunker_keeps_heading_and_fact_label_value_together(tmp_path):
    write_parsed(tmp_path, [base_doc()])
    chunks, report = chunk_parsed_documents(tmp_path, max_chars=150, overlap_chars=0)
    assert len(chunks) >= 1
    combined = "\n".join(c["text"] for c in chunks)
    assert "Scheme Details" in combined
    assert "Expense ratio | 0.50%" in combined
    assert "Minimum SIP | Rs 100" in combined
    assert report["chunk_count"] == len(chunks)


def test_chunker_splits_oversized_blocks_without_empty_chunks(tmp_path):
    long_text = " ".join([f"Sentence number {i}." for i in range(50)])
    pieces = _split_long_block(long_text, 100)
    assert len(pieces) > 1
    assert all(piece.strip() for piece in pieces)
    assert all(len(piece) <= 100 for piece in pieces)


def test_chunker_keeps_source_metadata_and_unique_ids(tmp_path):
    write_parsed(tmp_path, [base_doc(), base_doc("hdfc_mid_cap")])
    chunks, _ = chunk_parsed_documents(tmp_path, max_chars=150)
    ids = [chunk["chunk_id"] for chunk in chunks]
    assert len(ids) == len(set(ids))
    assert all(chunk["source_url"].startswith("https://groww.in/") for chunk in chunks)
    assert {chunk["source_id"] for chunk in chunks} == {"hdfc_large_cap", "hdfc_mid_cap"}


def test_chunker_does_not_mix_sections(tmp_path):
    doc = base_doc(sections=[
        {"section_title": "Fund Details", "blocks": ["Fund details content."]},
        {"section_title": "Risk Details", "blocks": ["Risk details content."]},
    ])
    write_parsed(tmp_path, [doc])
    chunks, _ = chunk_parsed_documents(tmp_path)
    assert len(chunks) == 2
    assert chunks[0]["section_title"] == "Fund Details"
    assert chunks[1]["section_title"] == "Risk Details"


def test_chunker_requires_parsed_input(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run `python -m app.parser` first"):
        chunk_parsed_documents(tmp_path)


def test_chunker_validates_overlap():
    with pytest.raises(ValueError):
        chunk_parsed_documents(Path("/tmp"), max_chars=200, overlap_chars=200)
