from app.config import load_config


def test_config_loads_five_approved_sources():
    config = load_config()
    sources = config["sources"]["urls"]

    assert len(sources) == 5
    assert config["sources"]["crawl_internal_links"] is False
    assert config["embedding"]["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert config["vector_db"]["provider"] == "chroma"



def test_llm_model_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen/qwen3.8-27b")
    config = load_config()
    assert config["llm"]["model"] == "qwen/qwen3.8-27b"
    assert config["llm"]["temperature"] == 0.2
