from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.co_agents.base import CoAgent
from internal.logger import logger
from internal.prompts import SYSTEM_PROMPT, get_prompt
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config_chain,
)

PROMPT_KEY = "PHILOSOPHER_PROMPT"
ENV_PREFIX = "PHILOSOPHER"


class PhilosopherCoAgent(CoAgent):
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX

    @classmethod
    def create(
        cls, base_config: AgentConfig, env: dict[str, str], http_client: AsyncClient
    ) -> "PhilosopherCoAgent":
        config = load_agent_config_chain(["MAIN", cls.ENV_PREFIX], base_config, env)
        model = create_openai_model(config, http_client)
        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=get_prompt(cls.PROMPT_KEY),
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        return cls(agent)

    def __init__(
        self,
        agent: Agent[None, str],
        history_limit: int = 30,
    ) -> None:
        super().__init__(agent)
        self._history: list[ModelRequest | ModelResponse] | None = None
        self._history_limit = history_limit

    async def run(
        self, 
        prompt: str, 
        message_history: list[ModelRequest | ModelResponse] | None = None
    ) -> str:
        if message_history is None:
            message_history = self._history
        result = await self.agent.run(prompt, message_history=message_history)
        self._history = result.all_messages()[-self._history_limit :]
        return result.output

    async def run_stream(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ):
        """Stream philosopher output while maintaining internal history."""
        if message_history is None:
            message_history = self._history
        collected = ""
        try:
            async with self.agent.run_stream(user_prompt=prompt, message_history=message_history) as result:
                async for chunk in result.stream_text(delta=True):
                    if not chunk:
                        continue
                    collected += chunk
                    yield chunk

                # update history after completion
                try:
                    self._history = result.all_messages()[-self._history_limit :]
                except Exception:
                    pass
                return
        except Exception:
            logger.exception("Philosopher stream failed; falling back to non-stream")

        if collected:
            # Avoid duplicating partial output; update history in the background.
            try:
                result = await self.agent.run(prompt, message_history=message_history)
                self._history = result.all_messages()[-self._history_limit :]
            except Exception:
                logger.exception("Philosopher non-stream fallback failed after partial stream")
            return

        try:
            result = await self.agent.run(prompt, message_history=message_history)
            self._history = result.all_messages()[-self._history_limit :]
            if result.output:
                yield result.output
        except Exception:
            logger.exception("Philosopher non-stream fallback failed")
