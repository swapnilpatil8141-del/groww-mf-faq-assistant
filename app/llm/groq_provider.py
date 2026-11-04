"""Groq implementation of the provider-neutral LLM interface."""
from __future__ import annotations

from typing import Any

from app.llm.base import LLMProvider


class GroqProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, timeout: float = 30.0):
        if not api_key:
            raise ValueError("GROQ_API_KEY is missing. Add it to your local .env file.")
        if not model:
            raise ValueError("LLM_MODEL or llm.model must be configured.")
        try:
            from groq import Groq
        except ImportError as exc:
            raise RuntimeError("The groq package is not installed. Run pip install -r requirements.txt.") from exc
        self.model = model
        self.client = Groq(api_key=api_key, timeout=timeout)

    def health_check(self) -> dict[str, Any]:
        """Check that the configured model appears in the account's live model list."""
        try:
            available = self.client.models.list()
            model_ids = {
                getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else None)
                for item in getattr(available, "data", available)
            }
            if self.model not in model_ids:
                return {
                    "ok": False,
                    "provider": "groq",
                    "model": self.model,
                    "message": "Configured model is not present in the active model list for this Groq account.",
                }
            return {
                "ok": True,
                "provider": "groq",
                "model": self.model,
                "message": "Groq credentials and model availability verified.",
            }
        except Exception as exc:
            # Do not expose SDK exception details; they may contain request metadata.
            return {
                "ok": False,
                "provider": "groq",
                "model": self.model,
                "message": f"Could not verify Groq model availability ({type(exc).__name__}).",
            }

    def generate(self, system_prompt: str, user_prompt: str, settings: dict[str, Any] | None = None) -> str:
        settings = settings or {}
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=float(settings.get("temperature", 0.2)),
                max_tokens=int(settings.get("max_tokens", 350)),
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("Groq returned an empty response.")
            return content.strip()
        except Exception as exc:
            # Keep secrets and user question out of exception messages and logs.
            raise RuntimeError(f"Groq response generation failed ({type(exc).__name__}).") from exc
