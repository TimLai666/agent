from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from internal.agents import MainAgent
from internal.app.handle_user_turn import create_runtime
from internal.logger import logger
from internal.services.agent_factory import AgentConfig, load_base_config
from internal.services.config_manager import normalize_base_url


@dataclass
class OpenAICompatibleModel:
    """OpenAI-compatible model override for programmatic use."""

    model_name: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.2


class Agent:
    """Programmatic SDK entrypoint.

    This class is the third usage mode in addition to CLI/GUI:
    import and instantiate directly in Python code.
    """

    def __init__(
        self,
        *,
        system_name: str | None = None,
        system_prompt_append: str | None = None,
        system_prompt_override: str | None = None,
        skill_root_dirs: list[str | Path] | None = None,
        use_default_tools: bool = True,
        extra_tools: list[Any] | None = None,
        mcp_servers: list[Any] | None = None,
        model: OpenAICompatibleModel | None = None,
        include_skill_tool: bool = True,
        include_subagent_tools: bool = True,
        additional_system_prompts: list[str] | None = None,
        auto_load_all_prompts: bool = True,
        start_mcp_servers: bool = True,
    ) -> None:
        self.system_name = system_name
        self.system_prompt_append = system_prompt_append
        self.system_prompt_override = system_prompt_override
        self.skill_root_dirs = [self._to_abs_path(p) for p in (skill_root_dirs or [])]
        self.use_default_tools = use_default_tools
        self.extra_tools = list(extra_tools or [])
        self.mcp_servers = mcp_servers
        self.model = model
        self.include_skill_tool = include_skill_tool
        self.include_subagent_tools = include_subagent_tools
        self.additional_system_prompts = additional_system_prompts
        self.auto_load_all_prompts = auto_load_all_prompts
        self.start_mcp_servers = start_mcp_servers

        self._http_client: AsyncClient | None = None
        self._main_agent: MainAgent | None = None
        self._runtime: Any | None = None
        self._mcp_stack: AsyncExitStack | None = None

    @staticmethod
    def _to_abs_path(raw_path: str | Path) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (Path.cwd() / path).resolve()

    @staticmethod
    def _summarize_exception(exc: Exception) -> str:
        current: BaseException | None = exc
        visited: set[int] = set()

        while current is not None and id(current) not in visited:
            visited.add(id(current))
            nested = getattr(current, "exceptions", None)
            if isinstance(nested, (list, tuple)) and nested:
                current = nested[0]
                continue
            if getattr(current, "__cause__", None) is not None:
                current = current.__cause__
                continue
            if getattr(current, "__context__", None) is not None:
                current = current.__context__
                continue
            break

        if current is None:
            return "Unknown error"
        return f"{type(current).__name__}: {current}"

    def _create_model_override(self) -> tuple[OpenAIChatModel | None, float | None]:
        if self.model is None:
            return None, None

        normalized = normalize_base_url(self.model.base_url)
        base_url = f"{normalized}/v1" if normalized else None
        provider = OpenAIProvider(
            base_url=base_url,
            api_key=self.model.api_key,
            http_client=self._http_client,
        )
        model = OpenAIChatModel(model_name=self.model.model_name, provider=provider)
        return model, float(self.model.temperature)

    async def start(self) -> None:
        if self._main_agent is not None:
            return

        self._http_client = AsyncClient(verify=False)
        base_config = load_base_config()
        model_override, temperature = self._create_model_override()

        if self.model is not None:
            base_config = AgentConfig(
                name="base",
                base_url=self.model.base_url,
                api_key=self.model.api_key,
                model_name=self.model.model_name,
                temperature=self.model.temperature,
            )

        self._main_agent = MainAgent.create(
            base_config,
            self._http_client,
            skill_root_dirs=self.skill_root_dirs,
            additional_system_prompts=self.additional_system_prompts,
            auto_load_all_prompts=self.auto_load_all_prompts,
            system_name=self.system_name,
            system_prompt_override=self.system_prompt_override,
            system_prompt_append=self.system_prompt_append,
            model_override=model_override,
            model_temperature=temperature,
            mcp_servers_override=self.mcp_servers,
            use_default_tools=self.use_default_tools,
            extra_tools=self.extra_tools,
            include_skill_tool=self.include_skill_tool,
            include_subagent_tools=self.include_subagent_tools,
        )
        self._runtime = create_runtime(self._main_agent)

        if self.start_mcp_servers:
            self._mcp_stack = AsyncExitStack()
            try:
                await self._mcp_stack.enter_async_context(
                    self._main_agent.agent.run_mcp_servers()
                )
            except Exception as exc:
                reason = self._summarize_exception(exc)
                logger.warning(
                    "MCP servers failed to start in programmatic Agent; continuing without MCP. Root cause: %s",
                    reason,
                )
                self._main_agent.agent._user_toolsets = []

    async def close(self) -> None:
        if self._mcp_stack is not None:
            await self._mcp_stack.aclose()
            self._mcp_stack = None

        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

        self._runtime = None
        self._main_agent = None

    async def run(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        if self._runtime is None:
            await self.start()
        if self._runtime is None:
            raise RuntimeError("Agent runtime 尚未初始化")
        return await self._runtime.handle_user_turn(prompt, message_history=message_history)

    def run_sync(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        return asyncio.run(self.run(prompt, message_history=message_history))

    def set_tool_event_callback(self, callback: Any) -> None:
        if self._main_agent is None:
            raise RuntimeError("Agent 尚未啟動，請先呼叫 start() 或 run()")
        self._main_agent.set_tool_event_callback(callback)

    @property
    def main_agent(self) -> MainAgent | None:
        return self._main_agent

    async def __aenter__(self) -> "Agent":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()
