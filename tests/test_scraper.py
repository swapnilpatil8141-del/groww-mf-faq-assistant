import json
from pathlib import Path

import pytest
import requests

from app.config import load_config
from app.scraper import APPROVED_URLS, scrape_sources, validate_sources


class FakeResponse:
    def __init__(self, url, status_code=200, html="<html><head><title>Test</title></head><body><h1>Fund</h1><a href='/other'>Other</a></body></html>"):
        self.url = url
        self.status_code = status_code
        self.content = html.encode("utf-8")
        self.text = html
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, fail_url=None, status=200):
        self.headers = {}
        self.calls = []
        self.fail_url = fail_url
        self.status = status

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == self.fail_url:
            raise requests.Timeout("simulated timeout")
        return FakeResponse(url, status_code=self.status)


def test_only_exact_five_approved_urls_are_accepted():
    config = load_config()
    validated = validate_sources(config["sources"]["urls"])
    assert len(validated) == 5
    assert {x["source_id"] for x in validated} == set(APPROVED_URLS)


def test_unapproved_or_modified_url_is_rejected():
    config = load_config()
    config["sources"]["urls"][0]["url"] = "https://groww.in/other-page"
    with pytest.raises(ValueError):
        validate_sources(config["sources"]["urls"])


def test_extra_source_is_rejected():
    config = load_config()
    config["sources"]["urls"].append(
        {"source_id": "extra", "url": "https://groww.in/extra"}
    )
    with pytest.raises(ValueError):
        validate_sources(config["sources"]["urls"])


def test_scraper_fetches_only_five_exact_urls_and_does_not_follow_redirects(tmp_path):
    config = load_config()
    fake = FakeSession()
    records = scrape_sources(config, project_root=tmp_path, session=fake)

    assert len(fake.calls) == 5
    assert {call[0] for call in fake.calls} == set(APPROVED_URLS.values())
    assert all(call[1]["allow_redirects"] is False for call in fake.calls)
    assert all(record["fetch_status"] == "success" for record in records)
    assert (tmp_path / "data/raw/source_metadata.json").exists()
    assert len(list((tmp_path / "data/raw").glob("*.html"))) == 5


def test_failure_does_not_stop_other_sources(tmp_path):
    config = load_config()
    failed_url = config["sources"]["urls"][0]["url"]
    fake = FakeSession(fail_url=failed_url)
    records = scrape_sources(config, project_root=tmp_path, session=fake)

    assert len(records) == 5
    assert sum(r["fetch_status"] == "success" for r in records) == 4
    assert records[0]["fetch_status"] == "failed"
    assert records[0]["error"].startswith("Timeout")
    saved = json.loads((tmp_path / "data/raw/source_metadata.json").read_text())
    assert len(saved) == 5


def test_redirect_is_not_followed(tmp_path):
    config = load_config()
    fake = FakeSession(status=302)
    records = scrape_sources(config, project_root=tmp_path, session=fake)

    assert len(fake.calls) == 5
    assert all(call[1]["allow_redirects"] is False for call in fake.calls)
    assert all(record["fetch_status"] == "failed" for record in records)
    assert all("Redirect response blocked" in record["error"] for record in records)
