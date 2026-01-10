from abc import ABC

from pydantic_ai import Agent


class SubAgent(ABC):
    def __init__(self, agent: Agent[None, str]) -> None:
        self.agent = agent

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
