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

    async def run_stream(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ):
        """Async generator that yields streamed text chunks from the underlying agent."""
        async with self.agent.run_stream(user_prompt=prompt, message_history=message_history) as result:
            async for chunk in result.stream_text(delta=True):
                if not chunk:
                    continue
                yield chunk
