"""Load scraped HTML files into standardized document records.

This phase reads local files produced by app.scraper. It performs no network
requests, does not parse HTML, and does not discover or follow links.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, load_config
from app.scraper import APPROVED_URLS

LOGGER = logging.getLogger(__name__)


def load_documents(
    project_root: Path = PROJECT_ROOT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load successful scraped pages into JSONL document objects.

    Expected inputs:
      data/raw/source_metadata.json
      data/raw/<source_id>.html

    Outputs:
      data/loaded/loaded_documents.jsonl
      data/loaded/load_report.json

    Failed scrape records and missing/empty files are skipped and reported.
    The loader never makes HTTP requests.
    """
    raw_dir = project_root / "data" / "raw"
    loaded_dir = project_root / "data" / "loaded"
    metadata_path = raw_dir / "source_metadata.json"

    if not metadata_path.is_file():
        raise FileNotFoundError(
            f"Scrape metadata not found: {metadata_path}. "
            "Run `python -m app.scraper` first."
        )

    try:
        scrape_records = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid scrape metadata JSON: {exc}") from exc

    if not isinstance(scrape_records, list):
        raise ValueError("Scrape metadata must contain a JSON array.")

    loaded_dir.mkdir(parents=True, exist_ok=True)
    documents: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for record in scrape_records:
        source_id = record.get("source_id")
        source_url = record.get("source_url")

        # Do not allow metadata to introduce extra pages or arbitrary paths.
        if source_id not in APPROVED_URLS:
            skipped.append(
                {"source_id": str(source_id), "reason": "Unapproved source_id."}
            )
            continue
        if source_id in seen_ids:
            skipped.append(
                {"source_id": source_id, "reason": "Duplicate source metadata record."}
            )
            continue
        seen_ids.add(source_id)

        if source_url != APPROVED_URLS[source_id]:
            skipped.append(
                {"source_id": source_id, "reason": "Source URL does not match allowlist."}
            )
            continue

        if record.get("fetch_status") != "success":
            skipped.append(
                {
                    "source_id": source_id,
                    "reason": f"Scrape status is {record.get('fetch_status')!r}; only successful pages are loaded.",
                }
            )
            continue

        # Use a deterministic filename derived from the allowlisted ID rather
        # than trusting a path supplied by metadata.
        raw_file = raw_dir / f"{source_id}.html"
        if not raw_file.is_file():
            skipped.append(
                {"source_id": source_id, "reason": "Expected raw HTML file is missing."}
            )
            continue

        try:
            page_content = raw_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            skipped.append(
                {"source_id": source_id, "reason": f"Could not read raw HTML: {exc}"}
            )
            continue

        if not page_content.strip():
            skipped.append(
                {"source_id": source_id, "reason": "Raw HTML file is empty."}
            )
            continue

        fetched_at = record.get("fetched_at")
        if not fetched_at:
            skipped.append(
                {"source_id": source_id, "reason": "Fetch timestamp is missing."}
            )
            continue

        document = {
            "page_content": page_content,
            "metadata": {
                "source_id": source_id,
                "source_title": record.get("source_title"),
                "source_url": source_url,
                "fetched_at": fetched_at,
                "http_status": record.get("http_status"),
                "content_sha256": record.get("content_sha256"),
                "raw_file": f"data/raw/{source_id}.html",
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        documents.append(document)

    # Explicitly report approved sources absent from the scrape manifest.
    for missing_id in sorted(set(APPROVED_URLS) - seen_ids):
        skipped.append(
            {"source_id": missing_id, "reason": "No scrape metadata record was found."}
        )

    output_path = loaded_dir / "loaded_documents.jsonl"
    with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
        for document in documents:
            output_file.write(json.dumps(document, ensure_ascii=False) + "\n")

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_source_count": len(APPROVED_URLS),
        "loaded_count": len(documents),
        "skipped_count": len(skipped),
        "loaded_source_ids": [doc["metadata"]["source_id"] for doc in documents],
        "skipped": skipped,
        "output_file": "data/loaded/loaded_documents.jsonl",
    }
    (loaded_dir / "load_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    LOGGER.info(
        "Document loading finished: %s loaded, %s skipped.",
        len(documents),
        len(skipped),
    )
    return documents, report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    documents, report = load_documents()
    print(
        f"Document loading completed: {len(documents)} loaded, "
        f"{report['skipped_count']} skipped."
    )
    print(f"Loaded documents: {PROJECT_ROOT / 'data' / 'loaded' / 'loaded_documents.jsonl'}")
    print(f"Load report: {PROJECT_ROOT / 'data' / 'loaded' / 'load_report.json'}")
    if report["skipped"]:
        print("Skipped sources:")
        for item in report["skipped"]:
            print(f"- {item['source_id']}: {item['reason']}")


if __name__ == "__main__":
    main()
