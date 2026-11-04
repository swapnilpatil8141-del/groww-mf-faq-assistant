"""Fetch only the five explicitly approved Groww pages.

This module deliberately:
- reads URLs only from config/config.yaml;
- validates them against a fixed allowlist;
- disables HTTP redirects;
- never parses links or follows internal URLs;
- saves raw HTML and source metadata for the next pipeline phase.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.config import PROJECT_ROOT, load_config

LOGGER = logging.getLogger(__name__)

APPROVED_URLS = {
    "hdfc_amc_overview": "https://groww.in/mutual-funds/amc/hdfc-mutual-funds",
    "hdfc_large_cap": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    "hdfc_flexi_cap": "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    "hdfc_elss": "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
    "hdfc_mid_cap": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
}

DEFAULT_TIMEOUT_SECONDS = 30
USER_AGENT = (
    "Mozilla/5.0 (compatible; GrowwFactsOnlyFAQPrototype/1.0; "
    "+https://example.invalid/bot-info)"
)


def validate_sources(configured_sources: list[dict[str, str]]) -> list[dict[str, str]]:
    """Reject added, altered, duplicate, or unapproved source URLs."""
    if len(configured_sources) != len(APPROVED_URLS):
        raise ValueError(
            f"Exactly {len(APPROVED_URLS)} approved URLs must be configured; "
            f"received {len(configured_sources)}."
        )

    seen_ids: set[str] = set()
    validated: list[dict[str, str]] = []

    for source in configured_sources:
        source_id = source.get("source_id", "")
        url = source.get("url", "")

        if source_id not in APPROVED_URLS:
            raise ValueError(f"Unapproved source_id: {source_id!r}")
        if url != APPROVED_URLS[source_id]:
            raise ValueError(f"URL for {source_id!r} does not match the approved URL.")
        if source_id in seen_ids:
            raise ValueError(f"Duplicate source_id: {source_id!r}")

        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "groww.in":
            raise ValueError(f"Only approved HTTPS Groww URLs are permitted: {url}")

        seen_ids.add(source_id)
        validated.append({"source_id": source_id, "url": url})

    if seen_ids != set(APPROVED_URLS):
        missing = sorted(set(APPROVED_URLS) - seen_ids)
        raise ValueError(f"Missing approved source(s): {', '.join(missing)}")

    return validated


def _page_title(html: str) -> str | None:
    """Extract the document title without following or requesting any links."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(" ", strip=True)

    heading = soup.find("h1")
    if heading:
        return heading.get_text(" ", strip=True)
    return None


def scrape_sources(
    config: dict[str, Any] | None = None,
    project_root: Path = PROJECT_ROOT,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Fetch each allowlisted page once and persist raw HTML + metadata.

    Redirects are disabled so a configured URL cannot cause a request to a
    different destination. A non-200 response is recorded as a failure.
    """
    config = config or load_config()
    if config.get("sources", {}).get("crawl_internal_links") is not False:
        raise ValueError("crawl_internal_links must be false.")

    sources = validate_sources(config.get("sources", {}).get("urls", []))
    raw_dir = project_root / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    http = session or requests.Session()
    owns_session = session is None
    http.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})
    records: list[dict[str, Any]] = []

    try:
        for source in sources:
            source_id = source["source_id"]
            url = source["url"]
            fetched_at = datetime.now(timezone.utc).isoformat()
            record: dict[str, Any] = {
                "source_id": source_id,
                "source_url": url,
                "fetched_at": fetched_at,
                "fetch_status": "failed",
                "http_status": None,
                "source_title": None,
                "raw_file": None,
                "content_sha256": None,
                "error": None,
            }

            try:
                # Important: no redirects, no link extraction, no recursive requests.
                response = http.get(
                    url,
                    timeout=timeout,
                    allow_redirects=False,
                )
                record["http_status"] = response.status_code

                if 300 <= response.status_code < 400:
                    raise requests.HTTPError(
                        "Redirect response blocked; scraper will not follow redirects."
                    )
                response.raise_for_status()

                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and "html" not in content_type:
                    raise ValueError(f"Expected HTML response, received {content_type!r}")

                html_bytes = response.content
                if not html_bytes:
                    raise ValueError("The page returned an empty response body.")

                # Decode using response encoding where possible; retain raw HTML text.
                html = response.text
                if not html.strip():
                    raise ValueError("The page returned an empty HTML document.")

                file_path = raw_dir / f"{source_id}.html"
                file_path.write_text(html, encoding="utf-8")

                record.update(
                    {
                        "fetch_status": "success",
                        "source_title": _page_title(html),
                        "raw_file": str(file_path.relative_to(project_root)),
                        "content_sha256": hashlib.sha256(html_bytes).hexdigest(),
                    }
                )
                LOGGER.info("Scraped approved source %s", source_id)

            except Exception as exc:  # Continue to the next approved URL.
                record["error"] = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("Failed to scrape %s: %s", source_id, record["error"])

            records.append(record)

    finally:
        if owns_session:
            http.close()

    metadata_path = raw_dir / "source_metadata.json"
    metadata_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    success_count = sum(item["fetch_status"] == "success" for item in records)
    LOGGER.info(
        "Scraping finished: %s/%s approved pages fetched successfully.",
        success_count,
        len(records),
    )
    return records


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    records = scrape_sources()
    successful = sum(item["fetch_status"] == "success" for item in records)
    print(f"Scraping completed: {successful}/{len(records)} approved pages successful.")
    print(f"Metadata: {PROJECT_ROOT / 'data' / 'raw' / 'source_metadata.json'}")
    for item in records:
        print(f"- {item['source_id']}: {item['fetch_status']} (HTTP {item['http_status']})")


if __name__ == "__main__":
    main()
