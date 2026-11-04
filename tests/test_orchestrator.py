from app.orchestrator import answer_question


MODEL_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"


class FakeProvider:
    def __init__(self, answer):
        self.answer = answer
        self.generated_prompt = None

    def health_check(self):
        return {"ok": True}

    def generate(self, system_prompt, user_prompt, settings=None):
        self.generated_prompt = user_prompt
        return self.answer


def fake_retriever(question, project_root, source_ids=None):
    return {
        "status": "ok",
        "trace_id": "trace-123",
        "results": [
            {
                "chunk_id": "hdfc_large_cap_001",
                "text": "The expense ratio is 0.75%.",
                "source_id": "hdfc_large_cap",
                "source_url": MODEL_URL,
                "scheme_name": "HDFC Large Cap Fund Direct Growth",
                "section_title": "Scheme details",
                "fetched_at": "2026-11-02T10:00:00+00:00",
                "distance": 0.1,
                "score": 0.9,
            }
        ],
    }


def test_orchestrator_returns_answer_with_verified_source_and_timestamp(tmp_path):
    provider = FakeProvider("The expense ratio is 0.75%.")
    result = answer_question(
        "What is the expense ratio of HDFC Large Cap Fund?",
        project_root=tmp_path,
        provider=provider,
        retriever_fn=fake_retriever,
    )
    assert result["status"] == "answered"
    assert result["answer"] == "The expense ratio is 0.75%."
    assert result["source"]["url"] == MODEL_URL
    assert result["source"]["fetched_at"] == "2026-11-02T10:00:00+00:00"
    assert result["retrieved_chunk_ids"] == ["hdfc_large_cap_001"]


def test_advice_question_is_refused_before_retrieval(tmp_path):
    def should_not_retrieve(*args, **kwargs):
        raise AssertionError("retriever must not be called for advice")
    result = answer_question(
        "Should I invest in HDFC Large Cap Fund?",
        project_root=tmp_path,
        provider=FakeProvider(""),
        retriever_fn=should_not_retrieve,
    )
    assert result["status"] == "refused"


def test_pii_question_is_blocked_before_retrieval(tmp_path):
    def should_not_retrieve(*args, **kwargs):
        raise AssertionError("retriever must not be called for PII")
    result = answer_question(
        "My email is user@example.com; what is the fund expense ratio?",
        project_root=tmp_path,
        provider=FakeProvider(""),
        retriever_fn=should_not_retrieve,
    )
    assert result["status"] == "blocked"


def test_no_retrieved_evidence_abstains(tmp_path):
    result = answer_question(
        "What is the expense ratio of HDFC Large Cap Fund?",
        project_root=tmp_path,
        provider=FakeProvider(""),
        retriever_fn=lambda *args, **kwargs: {"status": "no_evidence", "results": []},
    )
    assert result["status"] == "cannot_verify"


def test_unsupported_numeric_claim_is_not_displayed(tmp_path):
    provider = FakeProvider("The expense ratio is 0.95%.")
    result = answer_question(
        "What is the expense ratio of HDFC Large Cap Fund?",
        project_root=tmp_path,
        provider=provider,
        retriever_fn=fake_retriever,
    )
    assert result["status"] == "cannot_verify"
    assert result["reason"] == "answer_validation_failed"


def test_llm_health_check_failure_returns_safe_error(tmp_path):
    class UnhealthyProvider(FakeProvider):
        def health_check(self):
            return {"ok": False}
    result = answer_question(
        "What is the expense ratio of HDFC Large Cap Fund?",
        project_root=tmp_path,
        provider=UnhealthyProvider(""),
        retriever_fn=fake_retriever,
    )
    assert result["status"] == "service_error"
def test_orchestrator_passes_scheme_filter_to_retriever(tmp_path):
    captured = {}

    def checking_retriever(question, project_root, source_ids=None):
        captured["source_ids"] = source_ids
        return fake_retriever(
            question,
            project_root,
            source_ids=source_ids,
        )

    result = answer_question(
        "What is the lock-in period for HDFC ELSS Tax Saver Fund?",
        project_root=tmp_path,
        provider=FakeProvider("The fund has a lock-in period of 3 years."),
        retriever_fn=checking_retriever,
    )

    assert captured["source_ids"] == ["hdfc_elss"]