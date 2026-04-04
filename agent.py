from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator, Callable

from httpx import AsyncClient
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from internal.agents import MainAgent
from internal.logger import logger
from internal.memory import MemoryManager
from internal.paths import set_runtime_paths
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
        workspace: str | Path | None = None,
        memory_enabled: bool = True,
        memory_dir: str | Path | None = None,
        memory_system: MemoryManager | None = None,
        disabled_skills: list[str] | None = None,
        extra_mcp_servers: list[Any] | None = None,
    ) -> None:
        self.workspace_root = self._resolve_workspace_root(workspace)
        if self.workspace_root is not None:
            set_runtime_paths(sandbox_dir=self.workspace_root)

        self.system_name = system_name
        self.system_prompt_append = system_prompt_append
        self.system_prompt_override = system_prompt_override
        self.skill_root_dirs = [self._to_abs_path(p, self.workspace_root) for p in (skill_root_dirs or [])]
        self.use_default_tools = use_default_tools
        self.extra_tools = list(extra_tools or [])
        self.mcp_servers = mcp_servers
        self.model = model
        self.include_skill_tool = include_skill_tool
        self.include_subagent_tools = include_subagent_tools
        self.additional_system_prompts = additional_system_prompts
        self.auto_load_all_prompts = auto_load_all_prompts
        self.start_mcp_servers = start_mcp_servers
        self.disabled_skills = disabled_skills
        self.extra_mcp_servers = extra_mcp_servers

        # Memory system: use provided instance, or build one from flags/dir
        if memory_system is not None:
            self._memory_manager: MemoryManager | None = memory_system
        elif not memory_enabled:
            self._memory_manager = MemoryManager(enabled=False)
        else:
            self._memory_manager = MemoryManager(
                memory_dir=memory_dir,
                enabled=True,
            )

        self._http_client: AsyncClient | None = None
        self._main_agent: MainAgent | None = None
        self._mcp_stack: AsyncExitStack | None = None

    @staticmethod
    def _resolve_workspace_root(raw_path: str | Path | None) -> Path | None:
        if raw_path is None:
            return None
        return Path(raw_path).expanduser().resolve()

    @staticmethod
    def _to_abs_path(raw_path: str | Path, workspace_root: Path | None = None) -> Path:
        from internal.paths import TIM_AGENT_SANDBOX_DIR
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path.resolve()
        # 使用沙盒目錄作為 agent 的工作目錄，不暴露真實 CWD
        base = workspace_root or TIM_AGENT_SANDBOX_DIR
        return (base / path).resolve()

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
            memory_manager=self._memory_manager,
            disabled_skills=self.disabled_skills,
            extra_mcp_servers=self.extra_mcp_servers,
        )

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

        self._main_agent = None

    async def run(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        if self._main_agent is None:
            await self.start()
        if self._main_agent is None:
            raise RuntimeError("Main agent 尚未初始化")
        return await self._main_agent.coordinator_handle_user_turn(
            prompt,
            message_history=message_history,
        )

    async def run_stream(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> AsyncIterator[str]:
        if self._main_agent is None:
            await self.start()
        if self._main_agent is None:
            raise RuntimeError("Main agent 尚未初始化")

        async for chunk in self._main_agent.run_stream(
            prompt,
            message_history=message_history,
        ):
            yield chunk

    def run_sync(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        return asyncio.run(self.run(prompt, message_history=message_history))

    def run_stream_sync(
        self,
        prompt: str,
        on_chunk: Callable[[str], None],
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        async def _consume() -> str:
            chunks: list[str] = []
            async for chunk in self.run_stream(prompt, message_history=message_history):
                chunks.append(chunk)
                on_chunk(chunk)
            return "".join(chunks)

        return asyncio.run(_consume())

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
