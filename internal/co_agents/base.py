from abc import ABC

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse


class CoAgent(ABC):
    def __init__(self, agent: Agent[None, str]) -> None:
        self.agent = agent

    async def run(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        result = await self.agent.run(prompt, message_history=message_history)
        return result.output
