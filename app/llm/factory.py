"""LLM provider factory."""
from __future__ import annotations

from typing import Any

from app.llm.groq_provider import GroqProvider


def create_provider(config: dict[str, Any]):
    llm_config = config.get("llm", {})
    provider_name = str(llm_config.get("provider", "groq")).lower()
    if provider_name != "groq":
        raise ValueError(
            f"Unsupported LLM provider {provider_name!r}. The initial MVP implements Groq only."
        )
    return GroqProvider(
        api_key=llm_config.get("api_key") or "",
        model=llm_config.get("model") or "",
        timeout=float(llm_config.get("timeout_seconds", 30)),
    )
