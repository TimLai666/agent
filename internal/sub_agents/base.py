from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Optional

from pydantic_ai import Agent

if TYPE_CHECKING:
    from internal.co_agents.philosopher import PhilosopherCoAgent
    from internal.skills_loader import SkillRegistry

from internal.logger import logger


class SubAgent(ABC):
    def __init__(
        self,
        agent: Agent[None, str],
        philosopher: "PhilosopherCoAgent" | None = None,
        skills: Optional["SkillRegistry"] = None,
    ) -> None:
        self.agent = agent
        self._philosopher = philosopher
        self._skills = skills

    async def run(self, prompt: str) -> str:
        # Skills are now tool-based (use_skill tool) - no automatic injection
        result = await self.agent.run(prompt)
        return result.output

    async def run_stream(self, prompt: str):
        """Stream output from the underlying agent."""
        # Skills are now tool-based (use_skill tool) - no automatic injection
        async with self.agent.run_stream(user_prompt=prompt) as result:
            async for chunk in result.stream_text(delta=True):
                if not chunk:
                    continue
                yield chunk

    async def ask_philosopher(self, question: str) -> str:
        if not self._philosopher:
            raise RuntimeError("Philosopher co-agent is not available.")
        return await self._philosopher.run(question)
