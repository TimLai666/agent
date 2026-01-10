from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.co_agents.base import CoAgent
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

    async def run(self, prompt: str) -> str:
        result = await self.agent.run(prompt, message_history=self._history)
        self._history = result.all_messages()[-self._history_limit :]
        return result.output
