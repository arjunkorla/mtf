"""AI Research Engine (section 20) -- Phase 4.

DATA FIRST, CALCULATIONS SECOND, SIGNALS THIRD, SCORING FOURTH, AI EXPLANATION
LAST: this module runs strictly after the scoring/risk/scenario engines and
only narrates what they already computed. It never calculates a score.
"""

import re

from app.ai.prompt_templates import SYSTEM_PROMPT, build_user_prompt
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.base import AiProvider
from app.config import Settings, get_settings
from app.core.exceptions import AiProviderError
from app.logging_config import get_logger
from app.schemas.scanner import CandidateResponse

logger = get_logger(__name__)

REQUIRED_SECTIONS = [
    "WHY WAS THIS STOCK SELECTED?",
    "STRONGEST EVIDENCE",
    "CONFLICTING EVIDENCE",
    "INSTITUTIONAL FOOTPRINT PROXY",
    "KEY RISKS",
    "WHAT WOULD CONFIRM THE SETUP?",
    "WHAT WOULD INVALIDATE IT?",
    "POSITION SIZING EXPLANATION",
]


def get_ai_provider(settings: Settings | None = None) -> AiProvider | None:
    settings = settings or get_settings()
    if settings.ai_provider == "anthropic":
        return AnthropicProvider(settings)
    return None


def _build_structured_payload(candidate: CandidateResponse) -> dict:
    """Builds exactly the JSON described in section 20: market/technical/
    volume/fno/fundamental/news/sector data, score, risks, position sizing,
    scenarios, and data quality -- nothing else, nothing invented.
    """
    return candidate.model_dump(mode="json")


def _extract_numeric_tokens(text: str) -> set[str]:
    return set(re.findall(r"\d+\.\d+|\d{2,}", text))


def _numeric_tokens_from_payload(payload: dict) -> set[str]:
    import json

    raw = json.dumps(payload, default=str)
    return _extract_numeric_tokens(raw)


def _parse_sections(raw_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        matched_header = next((h for h in REQUIRED_SECTIONS if stripped.upper().startswith(h)), None)
        if matched_header:
            if current:
                sections[current] = "\n".join(buf).strip()
            current = matched_header
            buf = []
        elif current:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


async def generate_research_note(candidate: CandidateResponse, settings: Settings | None = None) -> dict:
    """Returns {"sections": {...}, "raw_text": str, "flagged_unverified_numbers": [...]}.

    If no AI provider is configured (AI_PROVIDER=none), returns a
    data-quality-safe placeholder rather than fabricating a narrative.
    """
    settings = settings or get_settings()
    provider = get_ai_provider(settings)

    payload = _build_structured_payload(candidate)

    if provider is None:
        logger.info("AI_PROVIDER=none; skipping AI research note for %s", candidate.symbol)
        return {
            "sections": {h: "AI research is not configured (AI_PROVIDER=none)." for h in REQUIRED_SECTIONS},
            "raw_text": None,
            "flagged_unverified_numbers": [],
        }

    user_prompt = build_user_prompt(payload)

    try:
        raw_text = await provider.generate_research_note(SYSTEM_PROMPT, user_prompt)
    except AiProviderError as exc:
        logger.error("AI research note generation failed for %s: %s", candidate.symbol, exc)
        return {
            "sections": {h: "AI research unavailable (provider error)." for h in REQUIRED_SECTIONS},
            "raw_text": None,
            "flagged_unverified_numbers": [],
        }

    sections = _parse_sections(raw_text)

    allowed_numbers = _numeric_tokens_from_payload(payload)
    response_numbers = _extract_numeric_tokens(raw_text)
    flagged = sorted(response_numbers - allowed_numbers)
    if flagged:
        logger.warning(
            "AI research note for %s contains numbers not found in source JSON: %s",
            candidate.symbol, flagged,
        )

    return {"sections": sections, "raw_text": raw_text, "flagged_unverified_numbers": flagged}
