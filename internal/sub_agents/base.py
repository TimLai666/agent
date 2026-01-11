from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

from pydantic_ai import Agent

if TYPE_CHECKING:
    from internal.co_agents.philosopher import PhilosopherCoAgent


class SubAgent(ABC):
    def __init__(
        self,
        agent: Agent[None, str],
        philosopher: "PhilosopherCoAgent" | None = None,
    ) -> None:
        self.agent = agent
        self._philosopher = philosopher

    async def run(self, prompt: str) -> str:
        result = await self.agent.run(prompt)
        return result.output

    async def run_stream(self, prompt: str):
        """Stream output from the underlying agent."""
        async with self.agent.run_stream(user_prompt=prompt) as result:
            async for chunk in result.stream_text(delta=True):
                if not chunk:
                    continue
                yield chunk

    async def ask_philosopher(self, question: str) -> str:
        if not self._philosopher:
            raise RuntimeError("Philosopher co-agent is not available.")
        return await self._philosopher.run(question)
