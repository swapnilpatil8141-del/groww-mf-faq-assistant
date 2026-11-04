"""Configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load YAML configuration and environment variables."""
    load_dotenv(ENV_PATH)

    path = config_path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    # Keep secrets in environment variables; never place secret values in YAML.
    llm_config = config.setdefault("llm", {})
    api_key_env = llm_config.get("api_key_env", "GROQ_API_KEY")
    llm_config["api_key"] = os.getenv(api_key_env)

    # Allow the model ID to be overridden locally without committing secrets
    # or changing the tracked YAML file.
    model_env = llm_config.get("model_env", "LLM_MODEL")
    configured_model = os.getenv(model_env)
    if configured_model:
        llm_config["model"] = configured_model

    llm_config.setdefault("temperature", 0.2)
    llm_config.setdefault("max_tokens", 350)
    llm_config.setdefault("timeout_seconds", 30)

    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    """Validate the minimum settings required to start the project."""
    required_sections = ["sources", "embedding", "vector_db", "llm", "retrieval", "answer"]
    missing = [section for section in required_sections if section not in config]
    if missing:
        raise ValueError(f"Missing configuration section(s): {', '.join(missing)}")

    urls = config["sources"].get("urls", [])
    if not urls:
        raise ValueError("No approved source URLs are configured.")

    for source in urls:
        if not source.get("source_id") or not source.get("url"):
            raise ValueError("Each source must include both source_id and url.")

    if config["embedding"].get("model") != "sentence-transformers/all-MiniLM-L6-v2":
        raise ValueError("Embedding model differs from the model specified in implementation.md.")

    if config["vector_db"].get("provider") != "chroma":
        raise ValueError("This implementation is configured for ChromaDB.")
