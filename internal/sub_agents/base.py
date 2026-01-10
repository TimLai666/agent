from abc import ABC

from pydantic_ai import Agent


class SubAgent(ABC):
    def __init__(self, agent: Agent[None, str]) -> None:
        self.agent = agent

    async def run(self, prompt: str) -> str:
        result = await self.agent.run(prompt)
        return result.output
