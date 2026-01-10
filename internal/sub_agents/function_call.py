import sys

from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio

from internal.prompts import SYSTEM_PROMPT, get_prompt
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config_chain,
)
from internal.set_tools import add_all_tools
from internal.sub_agents.base import SubAgent

FUNCTION_CALL_PROMPT_KEY = "FUNCTION_CALL_AGENT_PROMPT"
FUNCTION_CALL_ENV_PREFIX = "FUNCTION_CALL"

PROMPT_KEY = "SUB_AGENT_PROMPT"
ENV_PREFIX = "SUB"


class FunctionCallAgent:
    PROMPT_KEY = FUNCTION_CALL_PROMPT_KEY
    ENV_PREFIX = FUNCTION_CALL_ENV_PREFIX

    @classmethod
    def create(
        cls, base_config: AgentConfig, env: dict[str, str], http_client: AsyncClient
    ) -> "FunctionCallAgent":
        config = load_agent_config_chain(
            ["MAIN", "SUB", cls.ENV_PREFIX], base_config, env
        )
        model = create_openai_model(config, http_client)
        mcp_servers = cls._build_browser_mcp_servers(env, config)
        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=get_prompt(cls.PROMPT_KEY),
            tools=[],
            model_settings={"temperature": config.temperature},
            mcp_servers=mcp_servers,
        )
        add_all_tools(agent, config.model_name, config.base_url, config.api_key)
        return cls(agent)

    def __init__(self, agent: Agent[None, str]) -> None:
        self.agent = agent

    async def run(self, prompt: str) -> str:
        result = await self.agent.run(prompt)
        return result.output

    async def run_stream(self, prompt: str):
        async with self.agent.run_stream(user_prompt=prompt) as result:
            async for chunk in result.stream_text(delta=True):
                if not chunk:
                    continue
                yield chunk

    @staticmethod
    def _build_browser_mcp_servers(
        env: dict[str, str], config: AgentConfig
    ) -> list[MCPServerStdio]:
        mcp_env = env.copy()
        if config.api_key:
            mcp_env["OPENAI_API_KEY"] = config.api_key
        if config.base_url:
            mcp_env["OPENAI_BASE_URL"] = config.base_url
        if config.model_name:
            mcp_env["BROWSER_USE_LLM_MODEL"] = config.model_name

        headed_env = mcp_env.copy()
        headed_env["BROWSER_USE_HEADLESS"] = "false"
        browser_use_headed = MCPServerStdio(
            command=sys.executable,
            args=["-m", "browser_use.mcp.server"],
            env=headed_env,
            tool_prefix="browser_headed",
        )

        headless_env = mcp_env.copy()
        headless_env["BROWSER_USE_HEADLESS"] = "true"
        browser_use_headless = MCPServerStdio(
            command=sys.executable,
            args=["-m", "browser_use.mcp.server"],
            env=headless_env,
            tool_prefix="browser_headless",
        )

        return [browser_use_headed, browser_use_headless]


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
        config = load_agent_config_chain(["MAIN", cls.ENV_PREFIX], base_config, env)
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
            agent_name = type(self.function_call_agent).__name__
            print(f"[LOG] subagent({type(self).__name__}) -> {agent_name}: {task}")
            # use streaming if available
            if hasattr(self.function_call_agent, "run_stream"):
                collected = ""
                async for chunk in self.function_call_agent.run_stream(task):
                    collected += chunk
                return collected
            return await self.function_call_agent.run(task)
