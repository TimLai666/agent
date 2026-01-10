from httpx import AsyncClient
from pydantic_ai import Agent

from internal.agents.function_call_agent import FunctionCallAgent
from internal.prompts import SYSTEM_PROMPT, get_prompt
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config,
)
from internal.sub_agents.base import SubAgent

PROMPT_KEY = "SUB_AGENT_PROMPT"
ENV_PREFIX = "SUB"


class FunctionCallSubAgent(SubAgent):
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX

    @classmethod
    def create(
        cls,
        base_config: AgentConfig,
        env: dict[str, str],
        http_client: AsyncClient,
        function_call_agent: FunctionCallAgent,
    ) -> "FunctionCallSubAgent":
        config = load_agent_config(cls.ENV_PREFIX, base_config, env)
        model = create_openai_model(config, http_client)
        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=get_prompt(cls.PROMPT_KEY),
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        return cls(agent, function_call_agent)

    def __init__(
        self, agent: Agent[None, str], function_call_agent: FunctionCallAgent
    ) -> None:
        super().__init__(agent)
        self.function_call_agent = function_call_agent

        @self.agent.tool_plain
        async def run_function_call_agent(task: str) -> str:
            return await self.function_call_agent.run(task)
