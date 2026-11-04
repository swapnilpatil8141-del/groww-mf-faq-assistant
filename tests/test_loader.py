import json
from pathlib import Path

import pytest

from app.scraper import APPROVED_URLS
from app.loader import load_documents


def create_scrape_fixture(base: Path, source_ids=None):
    raw = base / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    ids = source_ids or list(APPROVED_URLS)

    records = []
    for source_id in ids:
        (raw / f"{source_id}.html").write_text(
            f"<html><head><title>{source_id}</title></head><body>Raw HTML {source_id}</body></html>",
            encoding="utf-8",
        )
        records.append(
            {
                "source_id": source_id,
                "source_url": APPROVED_URLS[source_id],
                "fetched_at": "2026-11-02T10:00:00+00:00",
                "fetch_status": "success",
                "http_status": 200,
                "source_title": f"Title {source_id}",
                "content_sha256": "sample-hash",
            }
        )
    (raw / "source_metadata.json").write_text(json.dumps(records), encoding="utf-8")
    return raw


def test_loads_all_successful_approved_raw_documents(tmp_path):
    create_scrape_fixture(tmp_path)
    documents, report = load_documents(tmp_path)

    assert len(documents) == 5
    assert report["loaded_count"] == 5
    assert report["skipped_count"] == 0
    assert all(doc["page_content"].startswith("<html>") for doc in documents)
    assert all(doc["metadata"]["source_url"] in APPROVED_URLS.values() for doc in documents)


def test_loaded_document_has_expected_metadata_and_raw_content(tmp_path):
    create_scrape_fixture(tmp_path, ["hdfc_large_cap"])
    documents, _ = load_documents(tmp_path)

    doc = documents[0]
    assert doc["metadata"]["source_id"] == "hdfc_large_cap"
    assert doc["metadata"]["source_title"] == "Title hdfc_large_cap"
    assert doc["metadata"]["source_url"] == APPROVED_URLS["hdfc_large_cap"]
    assert doc["metadata"]["fetched_at"] == "2026-11-02T10:00:00+00:00"
    assert "Raw HTML hdfc_large_cap" in doc["page_content"]


def test_failed_scrape_record_is_skipped(tmp_path):
    raw = create_scrape_fixture(tmp_path, ["hdfc_large_cap"])
    records = json.loads((raw / "source_metadata.json").read_text())
    records[0]["fetch_status"] = "failed"
    (raw / "source_metadata.json").write_text(json.dumps(records))

    documents, report = load_documents(tmp_path)
    assert documents == []
    assert report["skipped_count"] >= 1
    assert any("only successful pages" in item["reason"] for item in report["skipped"])


def test_missing_raw_file_is_skipped(tmp_path):
    raw = create_scrape_fixture(tmp_path, ["hdfc_large_cap"])
    (raw / "hdfc_large_cap.html").unlink()

    documents, report = load_documents(tmp_path)
    assert documents == []
    assert any("missing" in item["reason"] for item in report["skipped"])


def test_empty_raw_file_is_skipped(tmp_path):
    raw = create_scrape_fixture(tmp_path, ["hdfc_large_cap"])
    (raw / "hdfc_large_cap.html").write_text("  ", encoding="utf-8")

    documents, report = load_documents(tmp_path)
    assert documents == []
    assert "empty" in report["skipped"][0]["reason"]


def test_unapproved_source_is_skipped(tmp_path):
    raw = create_scrape_fixture(tmp_path, ["hdfc_large_cap"])
    records = json.loads((raw / "source_metadata.json").read_text())
    records[0]["source_id"] = "other_fund"
    records[0]["source_url"] = "https://groww.in/other"
    (raw / "source_metadata.json").write_text(json.dumps(records))

    documents, report = load_documents(tmp_path)
    assert documents == []
    assert "Unapproved" in report["skipped"][0]["reason"]


def test_missing_scrape_metadata_fails_with_actionable_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run `python -m app.scraper` first"):
        load_documents(tmp_path)


def test_loaded_documents_are_saved_as_jsonl(tmp_path):
    create_scrape_fixture(tmp_path, ["hdfc_large_cap", "hdfc_mid_cap"])
    documents, _ = load_documents(tmp_path)

    output = tmp_path / "data" / "loaded" / "loaded_documents.jsonl"
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == len(documents) == 2
    assert (tmp_path / "data" / "loaded" / "load_report.json").is_file()
