"""AI provider interface. The research engine talks only to this interface,
never to a specific vendor SDK, so swapping providers is a config change
(AI_PROVIDER env var), not a code change.
"""

from abc import ABC, abstractmethod


class AiProvider(ABC):
    @abstractmethod
    async def generate_research_note(self, system_prompt: str, user_prompt: str) -> str:
        """Returns raw text/JSON from the model. Callers parse the result."""
        raise NotImplementedError
