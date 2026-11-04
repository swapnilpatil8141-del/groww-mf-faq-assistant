
"""Online query orchestration: guardrails -> retrieval -> Groq -> validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, load_config
from app.guardrails import classify_question, validate_generated_answer
from app.llm.factory import create_provider
from app.retriever import retrieve


SYSTEM_PROMPT = """You are a facts-only HDFC Mutual Fund FAQ assistant.

STRICT RULES:
- Answer only using the evidence supplied in the user message. Do not use prior
  knowledge, browsing, assumptions, or general market knowledge.
- Do not invent or infer facts, values, dates, fees, returns, URLs, or citations.
- If the evidence does not directly support the requested fact, reply exactly:
  "I cannot verify that information from the available source content."
- Do not give investment advice, buy/sell/hold recommendations, suitability
  judgements, portfolio guidance, return comparisons, or return predictions.
- Do not calculate or compare investment returns.
- Keep the answer to no more than three short sentences.
- Do not include any URL, Markdown link, citation, or source label. The application
  attaches the verified source link separately.
- Do not ask for or repeat PAN, Aadhaar, account numbers, OTPs, email addresses,
  or phone numbers.

Return only the answer text, with no heading or explanation of these rules."""


def _allowed_source_urls(config: dict[str, Any]) -> set[str]:
    """Return the URLs configured as approved sources."""
    return {
        str(item.get("url"))
        for item in config.get("sources", {}).get("urls", [])
        if item.get("url")
    }


def _build_user_prompt(
    question: str,
    evidence: list[dict[str, Any]],
) -> str:
    """Build the evidence-only prompt sent to the LLM."""
    excerpts = []

    for item in evidence:
        excerpts.append(
            "CHUNK ID: " + str(item.get("chunk_id", "")) + "\n"
            "SOURCE ID: " + str(item.get("source_id", "")) + "\n"
            "SOURCE TITLE: " + str(item.get("scheme_name", "")) + "\n"
            "SECTION: " + str(item.get("section_title", "")) + "\n"
            "FETCHED AT: " + str(item.get("fetched_at", "")) + "\n"
            "TEXT:\n" + str(item.get("text", ""))
        )

    return (
        "USER QUESTION:\n"
        + question.strip()
        + "\n\nRETRIEVED EVIDENCE (use only this material):\n\n"
        + "\n\n--- EVIDENCE ITEM ---\n\n".join(excerpts)
    )


def answer_question(
    question: str,
    project_root: Path = PROJECT_ROOT,
    provider: Any | None = None,
    retriever_fn: Any | None = None,
) -> dict[str, Any]:
    """Run the complete facts-only question-answering workflow.

    The raw question is passed to retrieval and the model in memory only.
    It is deliberately not written to an application log or answer audit file.
    """

    # Phase 1: Apply question guardrails.
    classification = classify_question(question)

    if classification["status"] != "allowed":
        return {
            "status": classification["status"],
            "message": classification["message"],
            "reason": classification["reason"],
        }

    config = load_config()

    # Phase 2: Retrieve evidence from the relevant scheme only.
    retriever_fn = retriever_fn or retrieve
    matched_schemes = classification.get("matched_schemes") or []

    try:
        retrieval = retriever_fn(
            question,
            project_root=project_root,
            source_ids=matched_schemes or None,
        )

    except Exception as exc:
        return {
            "status": "service_error",
            "message": (
                "I couldn't access the knowledge base right now. Please check "
                "that Phase 5 embeddings and the Phase 6 ChromaDB collection "
                "are available, then try again."
            ),
            "reason": type(exc).__name__,
        }

    # Phase 3: Collect retrieval trace information.
    results = retrieval.get("results") or []

    retrieved_chunk_ids = [
        item.get("chunk_id")
        for item in results
        if item.get("chunk_id")
    ]

    retrieved_source_ids = list(
        dict.fromkeys(
            item.get("source_id")
            for item in results
            if item.get("source_id")
        )
    )

    if retrieval.get("status") != "ok" or not results:
        return {
            "status": "cannot_verify",
            "message": (
                "I cannot verify that information from the available source content."
            ),
            "reason": "no_relevant_evidence",
            "trace_id": retrieval.get("trace_id"),
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_source_ids": retrieved_source_ids,
        }

    # Phase 4: Select the highest-ranked source and use only its chunks.
    # This ensures the displayed citation matches the evidence sent to the model.
    selected_source_id = results[0].get("source_id")

    selected_source = [
        item
        for item in results
        if item.get("source_id") == selected_source_id
    ]

    citation = selected_source[0]

    source_url = citation.get("source_url")
    fetched_at = citation.get("fetched_at")

    evidence_text = "\n\n".join(
        str(item.get("text", ""))
        for item in selected_source
    )

    if not evidence_text.strip():
        return {
            "status": "cannot_verify",
            "message": (
                "I cannot verify that information from the available source content."
            ),
            "reason": "empty_evidence",
            "trace_id": retrieval.get("trace_id"),
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_source_ids": retrieved_source_ids,
        }

    # Phase 5: Validate the source URL.
    allowed_urls = _allowed_source_urls(config)

    if not source_url or source_url not in allowed_urls:
        return {
            "status": "cannot_verify",
            "message": (
                "I cannot verify that information from an approved source "
                "in the current collection."
            ),
            "reason": "unapproved_source",
            "trace_id": retrieval.get("trace_id"),
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_source_ids": retrieved_source_ids,
        }

    if not fetched_at:
        return {
            "status": "cannot_verify",
            "message": (
                "I cannot verify that information because the source "
                "retrieval date is unavailable."
            ),
            "reason": "missing_source_timestamp",
            "trace_id": retrieval.get("trace_id"),
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_source_ids": retrieved_source_ids,
        }

    # Phase 6: Generate an answer using the retrieved evidence.
    try:
        provider = provider or create_provider(config)

        health = provider.health_check()

        if not health.get("ok"):
            return {
                "status": "service_error",
                "message": (
                    "The configured answer-generation model is not currently "
                    "available. Please check your Groq API key and model setting."
                ),
                "reason": "llm_health_check_failed",
                "trace_id": retrieval.get("trace_id"),
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "retrieved_source_ids": retrieved_source_ids,
            }

        generated = provider.generate(
            SYSTEM_PROMPT,
            _build_user_prompt(question, selected_source),
            settings=config.get("llm", {}),
        )

    except Exception as exc:
        return {
            "status": "service_error",
            "message": (
                "I couldn't generate a verified answer right now. "
                "Please try again later."
            ),
            "reason": type(exc).__name__,
            "trace_id": retrieval.get("trace_id"),
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_source_ids": retrieved_source_ids,
        }

    # Phase 7: Validate the generated answer against the evidence.
    validation = validate_generated_answer(
        answer=generated,
        evidence_text=evidence_text,
        source_url=source_url,
        fetched_at=fetched_at,
        allowed_urls=allowed_urls,
        max_sentences=int(
            config.get("answer", {}).get("max_sentences", 3)
        ),
    )

    if not validation.get("ok"):
        return {
            "status": "cannot_verify",
            "message": (
                "I cannot verify that information from the available source content."
            ),
            "reason": "answer_validation_failed",
            "validation_reason": validation.get("reason"),
            "trace_id": retrieval.get("trace_id"),
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_source_ids": retrieved_source_ids,
        }

    # Phase 8: Return the verified answer and retrieval trace.
    return {
        "status": "answered",
        "answer": validation["answer"],
        "source": {
            "title": citation.get("scheme_name") or citation.get("source_id"),
            "url": source_url,
            "source_id": citation.get("source_id"),
            "fetched_at": fetched_at,
            "chunk_id": citation.get("chunk_id"),
        },
        "trace_id": retrieval.get("trace_id"),
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "retrieved_source_ids": retrieved_source_ids,
    }
