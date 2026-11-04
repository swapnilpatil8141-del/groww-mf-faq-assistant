
"""Parse loaded HTML documents into clean, section-aware text.

This module reads local JSONL output from app.loader. It does not access the
network or discover/follow links.

It extracts:
1. Visible HTML text organised into sections.
2. Selected structured facts from the page's own __NEXT_DATA__ JSON.

Structured facts are restricted to the configured source's own scheme.
Competitor data, including peerComparison, is deliberately ignored.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.config import PROJECT_ROOT

LOGGER = logging.getLogger(__name__)

REMOVE_SELECTORS = [
    "script", "style", "noscript", "svg", "iframe",
    "nav", "footer", "aside", "form", "button",
    "[role='navigation']", "[role='contentinfo']", "[aria-hidden='true']",
]

BLOCK_TAGS = {"p", "li", "tr", "dt", "dd", "blockquote", "pre"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

EXPECTED_SCHEME_TERMS = {
    "hdfc_large_cap": ("large cap",),
    "hdfc_flexi_cap": ("flexi cap",),
    "hdfc_elss": ("elss", "tax saver"),
    "hdfc_mid_cap": ("mid cap",),
}


def _clean_text(value: str) -> str:
    """Normalize whitespace while retaining meaningful punctuation."""
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _table_row_text(row: Tag) -> str:
    """Keep table labels and values together in a single text block."""
    cells = row.find_all(["th", "td"], recursive=False)

    if not cells:
        cells = row.find_all(["th", "td"])

    values = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]
    values = [value for value in values if value]

    if len(values) >= 2:
        return " | ".join(values)

    return values[0] if values else ""


def _normalise_name(value: Any) -> str:
    """Normalize a scheme name for conservative matching."""
    if not isinstance(value, str):
        return ""

    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _extract_page_scheme_data(html: str) -> dict[str, Any] | None:
    """Read mfServerSideData from the page's __NEXT_DATA__ script."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")

    if not script:
        return None

    raw_json = script.string or script.get_text()

    if not raw_json or not raw_json.strip():
        LOGGER.warning("__NEXT_DATA__ script is empty.")
        return None

    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        LOGGER.warning("Could not parse __NEXT_DATA__ JSON: %s", exc)
        return None

    if not isinstance(payload, dict):
        return None

    props = payload.get("props")
    if not isinstance(props, dict):
        return None

    page_props = props.get("pageProps")
    if not isinstance(page_props, dict):
        return None

    scheme_data = page_props.get("mfServerSideData")

    if not isinstance(scheme_data, dict):
        return None

    return scheme_data


def _matches_expected_scheme(
    scheme_data: dict[str, Any],
    source_id: str | None,
) -> bool:
    """Ensure embedded facts belong to the configured scheme page."""
    if not source_id:
        return False

    expected_terms = EXPECTED_SCHEME_TERMS.get(source_id)

    # Unknown sources, including the AMC overview, are not eligible.
    if not expected_terms:
        return False

    scheme_name = _normalise_name(scheme_data.get("scheme_name"))

    if not scheme_name:
        return False

    return any(
        _normalise_name(term) in scheme_name
        for term in expected_terms
    )


def _format_number(value: Any) -> str | None:
    """Return a clean numeric string, accepting numeric strings safely."""
    if isinstance(value, bool):
        return None

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return None

        try:
            value = float(value)
        except ValueError:
            return None

    if not isinstance(value, (int, float)):
        return None

    if value < 0:
        return None

    return f"{value:g}"


def _extract_lock_in_years(
    scheme_data: dict[str, Any],
) -> int | None:
    """Extract an explicitly supplied lock-in period from scheme data."""
    candidates: list[int] = []

    additional_details = scheme_data.get("additional_details")

    if isinstance(additional_details, dict):
        value = additional_details.get("lock_in_yrs")

        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 < value <= 20
        ):
            candidates.append(value)

    direct_value = scheme_data.get("lock_in_yrs")

    if (
        isinstance(direct_value, int)
        and not isinstance(direct_value, bool)
        and 0 < direct_value <= 20
    ):
        candidates.append(direct_value)

    unique_values = set(candidates)

    if len(unique_values) == 1:
        return next(iter(unique_values))

    if len(unique_values) > 1:
        LOGGER.warning(
            "Conflicting lock-in values found in scheme data; "
            "the lock-in fact was not extracted."
        )

    return None


def _extract_structured_facts(
    html: str,
    source_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract selected facts belonging to the page's own scheme."""
    scheme_data = _extract_page_scheme_data(html)

    if not scheme_data:
        return []

    if not _matches_expected_scheme(scheme_data, source_id):
        LOGGER.info(
            "Structured facts not extracted: embedded scheme did not match "
            "configured source_id '%s'.",
            source_id,
        )
        return []

    blocks: list[str] = []

    scheme_name = scheme_data.get("scheme_name")

    if isinstance(scheme_name, str) and scheme_name.strip():
        blocks.append(f"Scheme name: {_clean_text(scheme_name)}.")

    fund_house = scheme_data.get("fund_house")

    if isinstance(fund_house, str) and fund_house.strip():
        blocks.append(f"Fund house: {_clean_text(fund_house)}.")

    # Benchmark belongs to this scheme's own mfServerSideData.
    benchmark_name = scheme_data.get("benchmark_name")
    benchmark_code = scheme_data.get("benchmark")

    if isinstance(benchmark_name, str) and benchmark_name.strip():
        benchmark_text = _clean_text(benchmark_name)

        if (
            isinstance(benchmark_code, str)
            and benchmark_code.strip()
            and benchmark_code.strip().lower() != benchmark_text.lower()
        ):
            benchmark_text = (
                f"{benchmark_text} ({_clean_text(benchmark_code)})"
            )

        blocks.append(f"Benchmark: {benchmark_text}.")

    elif isinstance(benchmark_code, str) and benchmark_code.strip():
        blocks.append(f"Benchmark: {_clean_text(benchmark_code)}.")

    # Accept both numeric and string values for expense_ratio.
    # Do not read expense values from peerComparison.
    expense_ratio = _format_number(
        scheme_data.get("expense_ratio")
    )

    if expense_ratio is not None:
        blocks.append(
            "Expense ratio reported on the Groww source page: "
            f"{expense_ratio}%."
        )

    lock_in_years = _extract_lock_in_years(scheme_data)

    if lock_in_years is not None:
        blocks.append(f"Lock-in period: {lock_in_years} years.")

    if not blocks:
        return []

    return [
        {
            "section_title": "Structured scheme facts from source page",
            "blocks": blocks,
        }
    ]


def _find_content_root(soup: BeautifulSoup) -> Tag:
    """Prefer the page's main content container; fall back to body/document."""
    for selector in ["main", "article", "[role='main']"]:
        candidate = soup.select_one(selector)

        if candidate:
            return candidate

    return soup.body or soup


def extract_sections(
    html: str,
    fallback_title: str | None = None,
    source_id: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Extract visible text and selected structured facts."""
    # Extract structured facts before removing script tags.
    structured_sections = _extract_structured_facts(
        html,
        source_id=source_id,
    )

    soup = BeautifulSoup(html, "html.parser")

    title = ""

    if soup.title:
        title = _clean_text(soup.title.get_text(" ", strip=True))

    if not title:
        h1 = soup.find("h1")
        title = _clean_text(h1.get_text(" ", strip=True)) if h1 else ""

    title = title or fallback_title or "Untitled source"

    for selector in REMOVE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    content_root = _find_content_root(soup)

    sections: list[dict[str, Any]] = []
    current_title = title
    current_blocks: list[str] = []

    def flush() -> None:
        nonlocal current_blocks

        deduped: list[str] = []
        previous = None

        for block in current_blocks:
            if block and block != previous:
                deduped.append(block)

            previous = block

        if deduped:
            sections.append(
                {
                    "section_title": current_title,
                    "blocks": deduped,
                }
            )

        current_blocks = []

    # Walk meaningful block-level elements in DOM order.
    # Links are treated as text; their hrefs are never requested.
    for node in content_root.find_all(list(HEADING_TAGS | BLOCK_TAGS)):
        if node.name in HEADING_TAGS:
            heading = _clean_text(node.get_text(" ", strip=True))

            if heading:
                flush()
                current_title = heading

            continue

        if node.name == "tr":
            text = _table_row_text(node)
        else:
            text = _clean_text(node.get_text(" ", strip=True))

        if text:
            current_blocks.append(text)

    flush()

    # Conservative body-text fallback when no semantic blocks exist.
    if not sections:
        text = _clean_text(content_root.get_text(" ", strip=True))

        if text:
            sections = [
                {
                    "section_title": title,
                    "blocks": [text],
                }
            ]

    # Append validated structured facts as searchable sections.
    sections.extend(structured_sections)

    return title, sections


def parse_loaded_documents(
    project_root: Path = PROJECT_ROOT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse data/loaded/loaded_documents.jsonl into clean section records."""
    input_path = (
        project_root / "data" / "loaded" / "loaded_documents.jsonl"
    )

    output_dir = project_root / "data" / "parsed"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Loaded documents not found: {input_path}. "
            "Run `python -m app.loader` after successful scraping."
        )

    parsed_documents: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for line_number, line in enumerate(
        input_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue

        try:
            document = json.loads(line)
            metadata = document.get("metadata", {})
            html = document.get("page_content", "")

            if not isinstance(metadata, dict):
                raise ValueError("metadata is not an object")

            if not isinstance(html, str) or not html.strip():
                raise ValueError("page_content is empty or not text")

            title, sections = extract_sections(
                html,
                fallback_title=metadata.get("source_title"),
                source_id=metadata.get("source_id"),
            )

            if not sections:
                raise ValueError("No meaningful text blocks found")

            parsed_documents.append(
                {
                    "metadata": {
                        **metadata,
                        "source_title": metadata.get("source_title") or title,
                        "parsed_title": title,
                    },
                    "sections": sections,
                }
            )

        except Exception as exc:
            skipped.append(
                {
                    "line": str(line_number),
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    output_path = output_dir / "parsed_documents.jsonl"

    with output_path.open("w", encoding="utf-8") as output_file:
        for document in parsed_documents:
            output_file.write(
                json.dumps(document, ensure_ascii=False) + "\n"
            )

    report = {
        "parsed_count": len(parsed_documents),
        "skipped_count": len(skipped),
        "total_sections": sum(
            len(doc["sections"])
            for doc in parsed_documents
        ),
        "total_text_blocks": sum(
            len(section["blocks"])
            for doc in parsed_documents
            for section in doc["sections"]
        ),
        "skipped": skipped,
        "output_file": "data/parsed/parsed_documents.jsonl",
    }

    (output_dir / "parse_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    LOGGER.info(
        "Parsing finished: %s documents parsed, %s skipped.",
        len(parsed_documents),
        len(skipped),
    )

    return parsed_documents, report


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    documents, report = parse_loaded_documents()

    print(
        f"Parsing completed: {len(documents)} documents, "
        f"{report['total_sections']} sections, "
        f"{report['skipped_count']} skipped."
    )

    print(
        f"Output: {PROJECT_ROOT / 'data' / 'parsed' / 'parsed_documents.jsonl'}"
    )


if __name__ == "__main__":
    main()
