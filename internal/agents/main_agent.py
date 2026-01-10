from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.co_agents.philosopher import PhilosopherCoAgent
from internal.logger import logger
from internal.prompts import SYSTEM_PROMPT, get_prompt
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config_chain,
)
from internal.sub_agents.base import SubAgent

PROMPT_KEY = "MAIN_AGENT_PROMPT"
ENV_PREFIX = "MAIN"


class MainAgent:
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX

    @classmethod
    def create(
        cls,
        base_config: AgentConfig,
        env: dict[str, str],
        http_client: AsyncClient,
        philosopher: PhilosopherCoAgent,
        sub_agent: SubAgent,
    ) -> "MainAgent":
        config = load_agent_config_chain([cls.ENV_PREFIX], base_config, env)
        model = create_openai_model(config, http_client)
        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=get_prompt(cls.PROMPT_KEY),
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        return cls(agent, philosopher, sub_agent)

    def __init__(
        self,
        agent: Agent[None, str],
        philosopher: PhilosopherCoAgent,
        sub_agent: SubAgent,
    ) -> None:
        self.agent = agent
        self.philosopher = philosopher
        self.sub_agent = sub_agent

        @self.agent.tool_plain
        async def ask_philosopher(question: str) -> str:
            logger.info("Main agent -> philosopher")
            print("[LOG] main -> philosopher")
            return await self.philosopher.run(question)

        @self.agent.tool_plain
        async def delegate_to_subagent(task: str) -> str:
            subagent_name = type(self.sub_agent).__name__
            logger.info("Main agent -> subagent (%s): %s", subagent_name, task)
            print(f"[LOG] main -> subagent({subagent_name}): {task}")
            return await self.sub_agent.run(task)

    async def run(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        result = await self.agent.run(prompt, message_history=message_history)
        return result.output
