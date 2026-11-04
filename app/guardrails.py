"""Input classification and conservative response validation.

PII detection is heuristic, not a guarantee. Raw questions are never written
to application logs by this module or the orchestrator.
"""
from __future__ import annotations

import re
from typing import Any


PII_PATTERNS = [
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE),  # PAN
    re.compile(r"(?<!\d)\d{12}(?!\d)"),                       # Aadhaar-like 12 digits
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)"),   # Indian mobile
    re.compile(r"\b(?:otp|one[\s-]?time password)\s*[:=-]?\s*\d{4,8}\b", re.IGNORECASE),
    re.compile(r"\b(?:account|a/c|bank account)\s*(?:number|no\.?|#)?\s*[:=-]?\s*\d{8,18}\b", re.IGNORECASE),
]

ADVICE_PATTERNS = [
    re.compile(r"\bshould\s+i\s+(?:buy|sell|hold|invest)\b", re.IGNORECASE),
    re.compile(r"\b(?:buy|sell|hold)\s+(?:this|the|a|any|my)?\s*(?:fund|scheme|mutual fund|units?)?\b", re.IGNORECASE),
    re.compile(r"\b(?:best|better|ideal|right)\s+(?:fund|scheme|mutual fund)\s+for\s+me\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(?:fund|scheme)\s+should\s+i\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(?:hdfc\s+)?(?:fund|scheme)\s+(?:is\s+)?(?:the\s+)?best\s+for\s+me\b", re.IGNORECASE),
    re.compile(r"\b(?:portfolio|asset)\s+allocat(?:ion|e)\b", re.IGNORECASE),
    re.compile(r"\b(?:risk appetite|risk tolerance|suitab(?:le|ility))\b", re.IGNORECASE),
    re.compile(r"\b(?:highest|best|maximum)\s+returns?\b", re.IGNORECASE),
    re.compile(r"\bcompare\s+(?:the\s+)?returns?\b", re.IGNORECASE),
    re.compile(r"\breturn\s+(?:prediction|forecast|projection)\b", re.IGNORECASE),
]

RETURN_COMPARISON_PATTERNS = [
    re.compile(r"\bcompare\b.{0,50}\breturns?\b|\breturns?\b.{0,50}\bcompare\b", re.IGNORECASE),
    re.compile(r"\bwhich\b.{0,50}\b(?:highest|best|more)\s+returns?\b", re.IGNORECASE),
]

SCHEME_ALIASES = {
    "hdfc_large_cap": [
        "hdfc large cap", "hdfc large-cap", "large cap fund", "large-cap fund"
    ],
    "hdfc_flexi_cap": [
        "hdfc flexi cap", "hdfc flexicap", "flexi cap fund", "flexicap fund"
    ],
    "hdfc_elss": [
        "hdfc elss", "elss tax saver", "tax saver fund", "elss fund"
    ],
    "hdfc_mid_cap": [
        "hdfc mid cap", "hdfc mid-cap", "mid cap fund", "mid-cap fund"
    ],
}


def contains_pii(question: str) -> bool:
    return any(pattern.search(question) for pattern in PII_PATTERNS)


def _matched_schemes(question: str) -> list[str]:
    lowered = question.casefold()
    return [
        source_id
        for source_id, aliases in SCHEME_ALIASES.items()
        if any(alias in lowered for alias in aliases)
    ]


def classify_question(question: str) -> dict[str, Any]:
    """Classify and guard a question before retrieval."""
    if not isinstance(question, str) or not question.strip():
        return {"status": "blocked", "reason": "empty", "message": "Please enter a question."}

    if contains_pii(question):
        return {
            "status": "blocked",
            "reason": "pii",
            "message": "Please remove personal or account information and submit your question again. Do not enter PAN, Aadhaar, account numbers, OTPs, email addresses, or phone numbers.",
        }

    if any(pattern.search(question) for pattern in RETURN_COMPARISON_PATTERNS):
        return {
            "status": "refused",
            "reason": "return_comparison",
            "message": "I can provide factual scheme information, but I can't compare or predict investment returns.",
        }

    if any(pattern.search(question) for pattern in ADVICE_PATTERNS):
        return {
            "status": "refused",
            "reason": "investment_advice",
            "message": "I can provide factual information about a scheme, but I can't recommend whether you should buy, sell, hold, or invest in a fund, or assess its suitability for you.",
        }

    # Scope check: the prototype only covers the configured HDFC AMC page and
    # four named HDFC schemes. Avoid answering unrelated questions from model knowledge.
    lowered = question.casefold()
    in_scope = (
        "hdfc" in lowered
        or any(alias in lowered for aliases in SCHEME_ALIASES.values() for alias in aliases)
        or any(term in lowered for term in ("mutual fund", "scheme", "fund", "sip", "elss", "expense ratio", "exit load", "riskometer", "benchmark", "statement", "capital gains", "download"))
    )
    if not in_scope:
        return {
            "status": "out_of_scope",
            "reason": "unsupported_topic",
            "message": "I can answer factual questions only about the HDFC Mutual Fund pages currently in my source collection.",
        }

    schemes = _matched_schemes(question)
    asks_scheme_fact = any(
        term in lowered
        for term in ("expense ratio", "minimum sip", "sip amount", "lock-in", "lock in", "exit load", "benchmark", "riskometer", "minimum investment", "fund manager", "aum", "nav")
    )
    if asks_scheme_fact and len(schemes) == 0 and "amc" not in lowered and "hdfc mutual fund" not in lowered:
        return {
            "status": "clarification",
            "reason": "ambiguous_scheme",
            "message": "Which scheme do you mean: HDFC Large Cap, HDFC Flexi Cap, HDFC ELSS Tax Saver, or HDFC Mid Cap?",
        }

    return {
        "status": "allowed",
        "reason": "factual_query",
        "matched_schemes": schemes,
    }


def _sentence_count(text: str) -> int:
    # Treat common abbreviations and decimals as part of the same sentence.
    normalized = re.sub(r"\b(?:e\.g|i\.e|mr|mrs|dr)\.", "", text, flags=re.IGNORECASE)
    return len([part for part in re.split(r"(?<=[.!?])\s+", normalized.strip()) if part.strip()])


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[,]", "", value) for value in re.findall(r"(?<!\w)\d[\d,]*(?:\.\d+)?%?(?!\w)", text)}


def validate_generated_answer(
    answer: str,
    evidence_text: str,
    source_url: str,
    fetched_at: str | None,
    allowed_urls: set[str],
    max_sentences: int = 3,
) -> dict[str, Any]:
    """Validate answer shape, citation provenance, date, and numeric grounding."""
    if not isinstance(answer, str) or not answer.strip():
        return {"ok": False, "reason": "empty_answer"}

    # The application attaches the one source link. Reject model-supplied URLs
    # and Markdown links so the model cannot introduce a second citation.
    if re.search(r"https?://|www\.", answer, flags=re.IGNORECASE) or re.search(r"\[[^\]]+\]\([^)]+\)", answer):
        return {"ok": False, "reason": "model_supplied_citation"}

    clean = answer.strip()
    if _sentence_count(clean) > max_sentences:
        return {"ok": False, "reason": "too_many_sentences"}

    lowered = clean.casefold()
    unsafe_phrases = (
        "you should invest", "you should buy", "you should sell",
        "you should hold", "best fund for you", "suitable for you",
        "i recommend", "my recommendation",
    )
    if any(phrase in lowered for phrase in unsafe_phrases):
        return {"ok": False, "reason": "advice_language"}

    if not source_url or source_url not in allowed_urls:
        return {"ok": False, "reason": "unapproved_source"}
    if not fetched_at:
        return {"ok": False, "reason": "missing_source_timestamp"}

    # Conservative numerical check: every numeric token in the generated answer
    # must occur in the evidence excerpt. This does not prove semantic support.
    evidence_numbers = _numbers(evidence_text)
    answer_numbers = _numbers(clean)
    if not answer_numbers.issubset(evidence_numbers):
        return {"ok": False, "reason": "unsupported_numeric_claim"}

    return {"ok": True, "answer": clean}
