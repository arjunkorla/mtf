"""Anthropic (Claude) provider implementation.

Uses AI_API_KEY from settings; the key is never returned in any API
response (see core/security.py). Model id is configurable but defaults to
Claude Sonnet 5, Anthropic's current default-recommended model.
"""

from anthropic import AsyncAnthropic

from app.ai.providers.base import AiProvider
from app.config import Settings
from app.core.exceptions import AiProviderError
from app.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider(AiProvider):
    def __init__(self, settings: Settings, model: str = DEFAULT_MODEL):
        if not settings.ai_api_key:
            raise AiProviderError("AI_API_KEY is not set for AI_PROVIDER=anthropic")
        self._client = AsyncAnthropic(api_key=settings.ai_api_key)
        self._model = model

    async def generate_research_note(self, system_prompt: str, user_prompt: str) -> str:
        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=1500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - normalize all provider errors
            logger.error("Anthropic API call failed: %s", exc)
            raise AiProviderError(f"Anthropic API call failed: {exc}") from exc

        text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        if not text_blocks:
            raise AiProviderError("Anthropic response contained no text content")
        return "\n".join(text_blocks)
