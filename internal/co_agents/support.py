from httpx import AsyncClient
from pydantic_ai import Agent

from internal.co_agents.base import CoAgent
from internal.co_agents.philosopher import PhilosopherCoAgent
from internal.prompts import SYSTEM_PROMPT, get_prompt
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config,
)

PROMPT_KEY = "CO_AGENT_PROMPT"
ENV_PREFIX = "CO"


class SupportCoAgent(CoAgent):
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX

    @classmethod
    def create(
        cls,
        base_config: AgentConfig,
        env: dict[str, str],
        http_client: AsyncClient,
        philosopher: PhilosopherCoAgent,
    ) -> "SupportCoAgent":
        config = load_agent_config(cls.ENV_PREFIX, base_config, env)
        model = create_openai_model(config, http_client)
        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=get_prompt(cls.PROMPT_KEY),
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        return cls(agent, philosopher)

    def __init__(
        self, agent: Agent[None, str], philosopher: PhilosopherCoAgent
    ) -> None:
        super().__init__(agent)
        self.philosopher = philosopher

        @self.agent.tool_plain
        async def ask_philosopher(question: str) -> str:
            return await self.philosopher.run(question)
