"""Provider-neutral LLM interface for grounded answer generation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str, settings: dict[str, Any] | None = None) -> str:
        """Generate a response from supplied prompts."""

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Verify provider credentials and configured model availability."""
