import pytest

from app.guardrails import classify_question, contains_pii, validate_generated_answer


def test_classifies_supported_named_scheme_question():
    result = classify_question("What is the expense ratio of HDFC Large Cap Fund?")
    assert result["status"] == "allowed"
    assert result["matched_schemes"] == ["hdfc_large_cap"]


@pytest.mark.parametrize("question", [
    "Should I invest in HDFC Mid Cap Fund?",
    "Which fund is best for me?",
    "Compare returns of HDFC Large Cap and HDFC Mid Cap.",
])
def test_refuses_advice_and_return_comparison(question):
    assert classify_question(question)["status"] == "refused"


@pytest.mark.parametrize("question", [
    "My PAN is ABCDE1234F",
    "My Aadhaar is 123456789012",
    "Email swapnil@example.com",
    "Call me at 9876543210",
    "OTP: 123456",
    "My account number is 123456789012",
])
def test_blocks_pii_without_repeating_it(question):
    assert contains_pii(question)
    result = classify_question(question)
    assert result["status"] == "blocked"
    assert question not in result["message"]


def test_asks_for_scheme_when_fact_question_is_ambiguous():
    result = classify_question("What is the exit load?")
    assert result["status"] == "clarification"


def test_out_of_scope_question_is_not_sent_to_retrieval():
    result = classify_question("Who won the cricket match?")
    assert result["status"] == "out_of_scope"


def test_validates_one_app_attached_citation_and_timestamp():
    result = validate_generated_answer(
        "The expense ratio is 0.75%.",
        "The expense ratio is 0.75% as stated in the scheme details.",
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "2026-11-02T10:00:00+00:00",
        {"https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"},
    )
    assert result["ok"]


def test_rejects_unsupported_numeric_claim():
    result = validate_generated_answer(
        "The expense ratio is 0.95%.",
        "The expense ratio is 0.75%.",
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "2026-11-02T10:00:00+00:00",
        {"https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"},
    )
    assert not result["ok"]
    assert result["reason"] == "unsupported_numeric_claim"


def test_rejects_more_than_three_sentences():
    result = validate_generated_answer(
        "First. Second. Third. Fourth.",
        "Evidence.",
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "2026-11-02T10:00:00+00:00",
        {"https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"},
    )
    assert result["reason"] == "too_many_sentences"


def test_rejects_model_supplied_url():
    result = validate_generated_answer(
        "See https://example.com for details.",
        "Evidence.",
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "2026-11-02T10:00:00+00:00",
        {"https://groww.in/mutual-fund/hdfc-large-cap-fund-direct-growth"},
    )
    assert result["reason"] == "model_supplied_citation"
