"""Create section-aware chunks from parsed source documents."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, load_config

LOGGER = logging.getLogger(__name__)


def _split_long_block(text: str, max_chars: int) -> list[str]:
    """Split a long block at sentence/word boundaries without losing text."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            # Hard split only as a last resort, preferring whitespace boundaries.
            if current:
                pieces.append(current)
                current = ""
            remaining = sentence
            while len(remaining) > max_chars:
                cut = remaining.rfind(" ", 0, max_chars + 1)
                if cut <= 0:
                    cut = max_chars
                pieces.append(remaining[:cut].strip())
                remaining = remaining[cut:].strip()
            if remaining:
                current = remaining
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = sentence

    if current:
        pieces.append(current)
    return pieces


def chunk_parsed_documents(
    project_root: Path = PROJECT_ROOT,
    max_chars: int | None = None,
    overlap_chars: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Chunk parsed documents, preserving source and section context."""
    config = load_config()
    chunk_cfg = config.get("chunking", {})
    max_chars = max_chars or int(chunk_cfg.get("max_chars", 1200))
    overlap_chars = (
        int(chunk_cfg.get("overlap_chars", 0))
        if overlap_chars is None else overlap_chars
    )
    if max_chars < 100:
        raise ValueError("max_chars must be at least 100.")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be >= 0 and smaller than max_chars.")

    input_path = project_root / "data" / "parsed" / "parsed_documents.jsonl"
    output_dir = project_root / "data" / "chunks"
    output_dir.mkdir(parents=True, exist_ok=True)
    if not input_path.is_file():
        raise FileNotFoundError(
            f"Parsed documents not found: {input_path}. "
            "Run `python -m app.parser` first."
        )

    chunks: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for line_number, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            document = json.loads(line)
            metadata = document.get("metadata", {})
            source_id = metadata.get("source_id")
            if not source_id:
                raise ValueError("source_id is missing")

            for section_index, section in enumerate(document.get("sections", [])):
                section_title = section.get("section_title") or metadata.get("parsed_title") or "General"
                blocks = section.get("blocks", [])
                if not isinstance(blocks, list):
                    raise ValueError(f"Blocks are invalid in section {section_index}")

                # Keep complete blocks (including table label/value rows) together
                # whenever possible. Only split an individual oversized block.
                section_chunks: list[str] = []
                current = ""
                for block in blocks:
                    block = str(block).strip()
                    if not block:
                        continue
                    for piece in _split_long_block(block, max_chars):
                        candidate = f"{current}\n{piece}".strip() if current else piece
                        if len(candidate) <= max_chars:
                            current = candidate
                        else:
                            if current:
                                section_chunks.append(current)
                            current = piece
                if current:
                    section_chunks.append(current)

                # Optional overlap is disabled by default. When enabled, copy a
                # short trailing text window from the previous chunk.
                previous_text = ""
                for local_index, body in enumerate(section_chunks):
                    if local_index > 0 and overlap_chars:
                        overlap = previous_text[-overlap_chars:].strip()
                        if overlap and len(overlap) + len(body) + 1 <= max_chars:
                            body = f"{overlap}\n{body}"

                    chunk_index = len(chunks)
                    chunk_id = f"{source_id}_{chunk_index:04d}"
                    chunk_text = f"{section_title}\n{body}".strip()

                    chunks.append(
                        {
                            "chunk_id": chunk_id,
                            "source_id": source_id,
                            "source_title": metadata.get("source_title"),
                            "source_url": metadata.get("source_url"),
                            "section_title": section_title,
                            "section_index": section_index,
                            "chunk_index": chunk_index,
                            "fetched_at": metadata.get("fetched_at"),
                            "text": chunk_text,
                        }
                    )
                    previous_text = body

        except Exception as exc:
            skipped.append(
                {"line": str(line_number), "reason": f"{type(exc).__name__}: {exc}"}
            )

    output_path = output_dir / "chunks.jsonl"
    with output_path.open("w", encoding="utf-8") as output_file:
        for chunk in chunks:
            output_file.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    report = {
        "chunk_count": len(chunks),
        "skipped_document_count": len(skipped),
        "max_chars": max_chars,
        "overlap_chars": overlap_chars,
        "source_ids": sorted({chunk["source_id"] for chunk in chunks}),
        "skipped": skipped,
        "output_file": "data/chunks/chunks.jsonl",
    }
    (output_dir / "chunk_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    LOGGER.info("Chunking finished: %s chunks created, %s documents skipped.",
                len(chunks), len(skipped))
    return chunks, report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    chunks, report = chunk_parsed_documents()
    print(
        f"Chunking completed: {len(chunks)} chunks created, "
        f"{report['skipped_document_count']} documents skipped."
    )
    print(f"Output: {PROJECT_ROOT / 'data' / 'chunks' / 'chunks.jsonl'}")


if __name__ == "__main__":
    main()
