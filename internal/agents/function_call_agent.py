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

PROMPT_KEY = "FUNCTION_CALL_AGENT_PROMPT"
ENV_PREFIX = "FUNCTION_CALL"


class FunctionCallAgent:
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX

    @classmethod
    def create(
        cls, base_config: AgentConfig, env: dict[str, str], http_client: AsyncClient
    ) -> "FunctionCallAgent":
        config = load_agent_config_chain(["SUB", cls.ENV_PREFIX], base_config, env)
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
