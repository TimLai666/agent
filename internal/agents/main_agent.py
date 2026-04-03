import functools
import inspect
import re
import sys
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.messages import (
    BinaryContent,
    ImageUrl,
    ModelRequest,
    ModelResponse,
    UserContent,
)

from internal.logger import logger
from internal.prompts import (
    SYSTEM_PROMPT,
    build_runtime_instructions,
    build_environment_context,
    get_prompt,
    build_combined_system_prompt,
    list_available_system_prompts,
)
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config_chain,
)
from internal.services.config_manager import create_model_for_agent
from internal.services.subagent_tasks import (
    AgentToolInput,
    SendMessageToolInput,
    SubagentTaskManager,
    TaskStopToolInput,
)
from internal.set_tools import add_all_tools
from internal.skills_loader import SkillRegistry, load_skill_registry

from internal.mcp_server_list import get_all_mcp_servers
from internal.compaction import serialize_compaction_input
from internal.core.protocol.image_output_paths import (
    ImagePathStreamNormalizer,
    enforce_absolute_image_paths,
)

PROMPT_KEY = "MAIN_AGENT_PROMPT"
ENV_PREFIX = "MAIN"


class MainAgent:
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX
    _IMAGE_DIRECTIVE_RE = re.compile(r"(?mi)^\s*(?:image|img)\s*:\s*(?P<target>.+?)\s*$")
    _IMAGE_MARKDOWN_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")

    @staticmethod
    def _compose_agent_prompt(
        system_prompt: str,
        instructions: str | None,
    ) -> tuple[str, None]:
        merged_system_prompt = (system_prompt or "").strip()
        extra_instructions = (instructions or "").strip()

        if extra_instructions:
            if merged_system_prompt:
                merged_system_prompt = (
                    f"{merged_system_prompt}\n\n"
                    "## Runtime Instructions\n\n"
                    f"{extra_instructions}"
                )
            else:
                merged_system_prompt = extra_instructions

        return merged_system_prompt, None

    @classmethod
    def _build_enhanced_system_prompt(
        cls,
        additional_prompts: list[str] | None = None,
        auto_load_all: bool = True,
        model_name: str | None = None,
        system_name: str | None = None,
        system_prompt_override: str | None = None,
        system_prompt_append: str | None = None,
    ) -> str:
        """建立增強的 system prompt。

        Args:
            additional_prompts: 要加入的額外 system prompt 名稱列表
            auto_load_all: 是否自動載入所有可用的 system prompts（預設 True）
            model_name: 當前使用的模型名稱

        Returns:
            組合後的 system prompt
        """
        variables = {"SYSTEM_NAME": system_name} if system_name else None

        if auto_load_all and additional_prompts is None:
            additional_prompts = list_available_system_prompts()
            logger.info("Auto-loading %d system prompts", len(additional_prompts))

        active_model = model_name or "unknown"

        environment_context = build_environment_context()
        runtime_info = f"""
    # Model Information

- **Active Model**: {active_model}

    # Runtime Environment

    {environment_context}

**IMPORTANT**: Each user turn includes an auto-injected local timestamp. Use that timestamp as the primary time reference for the current reply.
"""

        base_prompt = (system_prompt_override or SYSTEM_PROMPT).strip()
        base_with_time = base_prompt + "\n\n" + runtime_info
        if system_prompt_append:
            base_with_time = base_with_time + "\n\n" + system_prompt_append.strip()

        if not additional_prompts:
            return build_combined_system_prompt(
                base_prompt=base_with_time,
                additional_prompts=None,
                separator="\n\n---\n\n",
                variables=variables,
            )

        return build_combined_system_prompt(
            base_prompt=base_with_time,
            additional_prompts=additional_prompts,
            separator="\n\n---\n\n",
            variables=variables,
        )

    @classmethod
    def create(
        cls,
        base_config: AgentConfig,
        http_client: AsyncClient,
        skills: SkillRegistry | None = None,
        skill_root_dirs: list[Path] | None = None,
        additional_system_prompts: list[str] | None = None,
        auto_load_all_prompts: bool = True,
        system_name: str | None = None,
        system_prompt_override: str | None = None,
        system_prompt_append: str | None = None,
        model_override: Any | None = None,
        model_temperature: float | None = None,
        mcp_servers_override: list[Any] | None = None,
        use_default_tools: bool = True,
        extra_tools: list[Callable[..., Any]] | None = None,
        include_skill_tool: bool = True,
        include_subagent_tools: bool = True,
    ) -> "MainAgent":
        # Load skills first
        if skills is None:
            try:
                skills = load_skill_registry(root_dirs=skill_root_dirs)
            except Exception:
                logger.exception("Failed to load skills; continuing without them")
                skills = SkillRegistry({}, None)

        # Apply MAIN-specific default temperature of 0.5 when MAIN_MODEL_TEMPERATURE is not set.
        main_defaults = AgentConfig(
            name="main",
            base_url=base_config.base_url,
            api_key=base_config.api_key,
            model_name=base_config.model_name,
            temperature=0.5,
        )
        config = load_agent_config_chain([cls.ENV_PREFIX], main_defaults)
        if model_override is not None:
            model = model_override
            if model_temperature is None:
                model_temperature = base_config.temperature
        else:
            model = create_openai_model(config, http_client)
        active_model_name = (
            getattr(model, "model_name", None)
            or getattr(model, "model", None)
            or config.model_name
        )
        instructions = build_runtime_instructions(
            get_prompt(cls.PROMPT_KEY),
            include_environment_context=False,
        )

        mcp_servers = (
            get_all_mcp_servers()
            if mcp_servers_override is None
            else list(mcp_servers_override)
        )

        # 建立增強的 system prompt（預設自動載入所有可用的 prompts）
        enhanced_system_prompt = cls._build_enhanced_system_prompt(
            additional_prompts=additional_system_prompts,
            auto_load_all=auto_load_all_prompts,
            model_name=active_model_name,
            system_name=system_name,
            system_prompt_override=system_prompt_override,
            system_prompt_append=system_prompt_append,
        )
        agent_system_prompt, agent_instructions = cls._compose_agent_prompt(
            enhanced_system_prompt,
            instructions,
        )

        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=agent_system_prompt,
            instructions=agent_instructions,
            tools=[],
            model_settings={"temperature": model_temperature if model_temperature is not None else config.temperature},
            toolsets=mcp_servers,
        )

        # register global tools directly on the main agent
        # Wrap agent.tool_plain temporarily so that each registered tool is
        # wrapped to log calls, arguments, results and exceptions.
        original_tool_plain = getattr(agent, "tool_plain", None)
        if original_tool_plain:

            def logging_tool_plain(func=None, /, **kwargs):
                if func is None:

                    def decorator(inner):
                        return logging_tool_plain(inner, **kwargs)

                    return decorator

                # create a wrapped callable that logs on invocation
                if inspect.iscoroutinefunction(func):

                    @functools.wraps(func)
                    async def wrapped_async(*args, **kwargs):
                        callback = getattr(agent, "_tool_event_callback", None)
                        if callback:
                            try:
                                callback({"stage": "start", "tool": func.__name__, "args": args, "kwargs": kwargs})
                            except Exception as exc:
                                logger.debug("Tool event callback failed on start.", exc_info=True)
                        logger.info(
                            "Tool call start: %s args=%s kwargs=%s",
                            func.__name__,
                            args,
                            kwargs,
                        )
                        try:
                            res = await func(*args, **kwargs)
                            logger.info(
                                "Tool call end: %s result=%s", func.__name__, res
                            )
                            if callback:
                                try:
                                    callback({"stage": "end", "tool": func.__name__, "args": args, "kwargs": kwargs, "result": res})
                                except Exception as exc:
                                    logger.debug("Tool event callback failed on end.", exc_info=True)
                            return res
                        except Exception as exc:
                            logger.exception(
                                "Tool %s raised an exception", func.__name__
                            )
                            if callback:
                                try:
                                    callback({"stage": "error", "tool": func.__name__, "args": args, "kwargs": kwargs, "error": str(exc)})
                                except Exception as exc:
                                    logger.debug("Tool event callback failed on error.", exc_info=True)
                            raise

                    wrapped_callable = wrapped_async
                else:

                    @functools.wraps(func)
                    def wrapped_sync(*args, **kwargs):
                        callback = getattr(agent, "_tool_event_callback", None)
                        if callback:
                            try:
                                callback({"stage": "start", "tool": func.__name__, "args": args, "kwargs": kwargs})
                            except Exception as exc:
                                logger.debug("Tool event callback failed on start.", exc_info=True)
                        logger.info(
                            "Tool call start: %s args=%s kwargs=%s",
                            func.__name__,
                            args,
                            kwargs,
                        )
                        try:
                            res = func(*args, **kwargs)
                            logger.info(
                                "Tool call end: %s result=%s", func.__name__, res
                            )
                            if callback:
                                try:
                                    callback({"stage": "end", "tool": func.__name__, "args": args, "kwargs": kwargs, "result": res})
                                except Exception as exc:
                                    logger.debug("Tool event callback failed on end.", exc_info=True)
                            return res
                        except Exception as exc:
                            logger.exception(
                                "Tool %s raised an exception", func.__name__
                            )
                            if callback:
                                try:
                                    callback({"stage": "error", "tool": func.__name__, "args": args, "kwargs": kwargs, "error": str(exc)})
                                except Exception as exc:
                                    logger.debug("Tool event callback failed on error.", exc_info=True)
                            raise

                    wrapped_callable = wrapped_sync

                # delegate to the original registration API with the wrapped callable
                return original_tool_plain(wrapped_callable, **kwargs)

            cast(Any, agent).tool_plain = logging_tool_plain

        main_agent = cls(
            agent,
            skills,
            http_client,
            skill_root_dirs,
        )
        try:
            # Register skill tool inside wrapped phase so skill activations
            # also emit start/end/error events for GUI/CLI display.
            if include_skill_tool:
                from internal.tools.skill_tools import register_skill_tool

                register_skill_tool(agent, skills)
            if use_default_tools:
                add_all_tools(agent, extra_tools=extra_tools)
            elif extra_tools:
                for tool in extra_tools:
                    agent.tool_plain(tool)
            if include_subagent_tools:
                main_agent._register_subagent_tools()
            logger.info("Registered tools on MainAgent")
        except Exception:
            logger.exception(
                "Failed to add tools to main agent; continuing without external tools"
            )
        finally:
            # restore original registration function if we replaced it
            if original_tool_plain:
                cast(Any, agent).tool_plain = original_tool_plain
        return main_agent

    def __init__(
        self,
        agent: Agent[None, str],
        skills: SkillRegistry | None = None,
        http_client: AsyncClient | None = None,
        skill_root_dirs: list[Path] | None = None,
    ) -> None:
        self.agent = agent
        self.sub_agents = None
        self.skills = skills
        self._last_messages: list[ModelRequest | ModelResponse] | None = None
        self._last_execution_steps: list[dict[str, Any]] = []
        self._last_user_prompt: str | None = None
        self._previous_user_prompt: str | None = None
        self._last_assistant_reply: str | None = None
        self._http_client = http_client  # 保存以便重載 model
        self.skill_root_dirs = list(skill_root_dirs or [])
        self._session_id = str(uuid.uuid4())
        self._task_notifications: list[str] = []
        self._task_manager = SubagentTaskManager(
            worker=self._run_subagent_task,
            enqueue_notification=self._enqueue_pending_notification,
        )
        setattr(self.agent, "_tool_event_callback", None)
        # tools are registered via add_all_tools during create()

    def _register_subagent_tools(self) -> None:
        @self.agent.tool_plain
        async def AgentTool(
            prompt: str,
            name: str = "",
            subagent_type: str = "",
            run_in_background: bool = True,
            isolation: str = "none",
            model: str = "",
        ) -> dict[str, str]:
            """Create a subagent task. Supports spawn (with subagent_type) and fork (without)."""
            payload = AgentToolInput(
                prompt=prompt,
                name=name or None,
                subagent_type=subagent_type or None,
                run_in_background=run_in_background,
                isolation=cast(Any, isolation or "none"),
                model=model or None,
            )
            return cast(dict[str, str], await self._task_manager.spawnAgentTask(payload, self._session_id))

        @self.agent.tool_plain
        def SendMessageTool(to: str, message: str) -> dict[str, str | bool]:
            """Send a follow-up instruction to an existing subagent task."""
            payload = SendMessageToolInput(to=to, message=message)
            return self._task_manager.sendMessageToTask(payload, self._session_id)

        @self.agent.tool_plain
        def TaskStopTool(task_id: str) -> dict[str, str | bool]:
            """Stop a running or waiting subagent task."""
            payload = TaskStopToolInput(task_id=task_id)
            return self._task_manager.stopTask(payload)

        @self.agent.tool_plain
        def ListSubagentTasks() -> list[dict[str, str | int | bool | None]]:
            """List current subagent tasks for this coordinator session."""
            return self._task_manager.listTasks(self._session_id)

    def _enqueue_pending_notification(self, xml: str) -> None:
        self._task_notifications.append(xml)

    def _drain_task_notifications(self) -> list[str]:
        if not self._task_notifications:
            return []
        items = list(self._task_notifications)
        self._task_notifications.clear()
        return items

    def _inject_task_notifications(self, prompt: str) -> str:
        notifications = self._drain_task_notifications()
        if not notifications:
            return prompt
        joined = "\n".join(notifications)
        return (
            "<internal-task-notifications>\n"
            f"{joined}\n"
            "</internal-task-notifications>\n\n"
            f"{prompt}"
        )

    def _resolve_subagent_type(self, task_type: str | None) -> str:
        if task_type:
            return task_type
        return "general-purpose"

    async def _run_subagent_task(self, task: Any, prompt: str) -> str:
        if not self._http_client:
            raise RuntimeError("http_client unavailable for subagent execution")

        subagent_type = self._resolve_subagent_type(getattr(task, "subagentType", None))
        mode = getattr(task, "mode", "spawn")
        enable_tools = subagent_type not in {"compaction", "verification"}

        if mode == "fork":
            model = getattr(self.agent, "_model", None) or getattr(self.agent, "model", None)
            worker_system_prompt = getattr(self.agent, "system_prompt", "")
            worker_instructions = getattr(self.agent, "instructions", "")
            if model is None:
                raise RuntimeError("Fork subagent requires coordinator model")
        else:
            category = f"sub-agent/{subagent_type}"
            model = create_model_for_agent(
                agent_name=f"subagent:{subagent_type}",
                http_client=self._http_client,
                category=category,
            )
            if model is None:
                model = create_model_for_agent(
                    agent_name="default",
                    http_client=self._http_client,
                    category=None,
                )
            if model is None:
                raise RuntimeError("Unable to resolve model for subagent")

            if subagent_type == "compaction":
                worker_system_prompt = (
                    "You are a compaction subagent. "
                    "Respond with text only and do not call any tools."
                )
                worker_instructions = (
                    "Summarize context accurately without changing task intent. "
                    "Do not ask questions."
                )
            elif subagent_type == "verification":
                worker_system_prompt = (
                    "You are an independent verification agent. "
                    "CRITICAL: This is VERIFICATION-ONLY. "
                    "You cannot edit, write, or create project files. "
                    "You must return VERDICT: PASS, VERDICT: FAIL, or VERDICT: PARTIAL."
                )
                worker_instructions = (
                    "Verify claims with commands and concrete evidence. "
                    "Do not provide user-facing messaging."
                )
            else:
                worker_system_prompt = self._build_enhanced_system_prompt(
                    additional_prompts=None,
                    auto_load_all=True,
                    model_name=getattr(model, "model_name", None),
                )
                worker_instructions = (
                    f"You are subagent '{subagent_type}'. Focus only on assigned task and report concise results."
                )

        worker_system_prompt, worker_request_instructions = self._compose_agent_prompt(
            worker_system_prompt,
            worker_instructions,
        )

        worker: Agent[None, str] = Agent(
            model=model,
            system_prompt=worker_system_prompt,
            instructions=worker_request_instructions,
            tools=[],
            model_settings={"temperature": 0.2},
        )
        if enable_tools:
            add_all_tools(worker)

        result = await worker.run(prompt)
        return result.output or ""

    async def run_compaction_subagent(self, job: Any, prompt: str) -> str:
        if not self._http_client:
            raise RuntimeError("http_client unavailable for compaction")

        model = create_model_for_agent(
            agent_name="subagent:compaction",
            http_client=self._http_client,
            category="sub-agent/compaction",
        )
        if model is None:
            model = create_model_for_agent(
                agent_name="default",
                http_client=self._http_client,
                category=None,
            )
        if model is None:
            raise RuntimeError("Unable to resolve model for compaction subagent")

        worker_system_prompt, worker_request_instructions = self._compose_agent_prompt(
            prompt,
            (
                "You are the dedicated context compaction subagent. "
                "Output only plain text with <analysis> and <summary> blocks. "
                "No tool calls are allowed."
            ),
        )

        worker: Agent[None, str] = Agent(
            model=model,
            system_prompt=worker_system_prompt,
            instructions=worker_request_instructions,
            tools=[],
            model_settings={"temperature": 0.0},
        )

        input_text = serialize_compaction_input(job)
        result = await worker.run(input_text)
        return result.output or ""

    def set_tool_event_callback(self, callback) -> None:
        """Register a callback for tool execution events."""
        setattr(self.agent, "_tool_event_callback", callback)

    def _reload_model_from_db(self) -> None:
        """Pick up any model config changes made via the UI since the last call."""
        if not self._http_client:
            logger.warning("無法重載 model：沒有 http_client")
            return

        try:
            config = AgentConfig(
                name="main",
                base_url=None,
                api_key=None,
                model_name="",
                temperature=0.5,
            )
            new_model = create_openai_model(config, self._http_client)

            self.agent._model = new_model
            
            logger.debug("已從資料庫重載 model 配置")
        except Exception:
            logger.exception("重載 model 配置失敗，繼續使用現有配置")

    def _extract_user_reply(self, output: str | None) -> str | None:
        if not output:
            return None
        text = output
        if "<self-validation>" in text:
            text = text.split("<self-validation>", 1)[0]
        return text.strip() or None

    def _normalize_image_directives(self, prompt: str) -> str:
        if not prompt:
            return prompt

        def replace_directive(match: re.Match) -> str:
            target = match.group("target").strip()
            return f"![image]({target})"

        return self._IMAGE_DIRECTIVE_RE.sub(replace_directive, prompt)

    def _resolve_image_content(self, target: str) -> tuple[UserContent | None, str | None]:
        raw_target = (target or "").strip()
        if not raw_target:
            return None, "圖片參照為空。"
        if raw_target.startswith("<") and raw_target.endswith(">"):
            raw_target = raw_target[1:-1].strip()
        raw_target = raw_target.strip().strip("\"'").strip()

        if raw_target.startswith("data:"):
            try:
                content = BinaryContent.from_data_uri(raw_target)
            except Exception as exc:
                return None, f"圖片 data URI 無效：{exc}"
            if not content.is_image:
                return None, "Data URI 不是圖片格式。"
            return content, None

        if re.match(r"^https?://", raw_target, flags=re.IGNORECASE):
            return ImageUrl(raw_target), None

        if raw_target.lower().startswith("file://"):
            raw_target = raw_target[7:]

        try:
            content = BinaryContent.from_path(Path(raw_target))
        except Exception as exc:
            return None, f"無法讀取圖片 '{raw_target}': {exc}"
        if not content.is_image:
            return None, f"不支援的圖片格式 '{raw_target}' (media_type={content.media_type})."
        return content, None

    def _build_user_prompt_content(self, prompt: str) -> tuple[list[UserContent], list[str]]:
        normalized = self._normalize_image_directives(prompt)
        parts: list[UserContent] = []
        errors: list[str] = []
        last = 0
        for match in self._IMAGE_MARKDOWN_RE.finditer(normalized):
            if match.start() > last:
                parts.append(normalized[last:match.start()])
            target = match.group("target")
            content, error = self._resolve_image_content(target)
            if error:
                errors.append(error)
                parts.append(match.group(0))
            elif content is not None:
                parts.append(content)
            last = match.end()
        if last < len(normalized):
            parts.append(normalized[last:])
        if not parts:
            parts = [normalized]
        if errors:
            parts.append("\n\n[圖片載入錯誤]\n" + "\n".join(errors))
        return parts, errors

    def _append_error_to_user_content(
        self,
        content: list[UserContent],
        error_context: str,
    ) -> list[UserContent]:
        return [*content, error_context]

    def _inject_local_timestamp(self, prompt: str) -> str:
        """Inject per-turn local timestamp into user prompt context."""
        dt = datetime.now().astimezone()
        weekday_en = (
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        )[dt.weekday()]
        weekday_zh = ("週一", "週二", "週三", "週四", "週五", "週六", "週日")[dt.weekday()]
        tz_name = dt.tzname() or "local"

        return (
            "[LOCAL_TIMESTAMP_FOR_THIS_USER_TURN]\n"
            f"- datetime: {dt.isoformat(timespec='seconds')}\n"
            f"- timezone: {tz_name}\n"
            f"- weekday: {weekday_en} / {weekday_zh}\n\n"
            f"{prompt}"
        )

    async def run(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        skip_plan_execution: bool = True,
    ) -> str:
        from internal.app.handle_user_turn import create_runtime

        _ = skip_plan_execution  # backward compatibility
        runtime = create_runtime(self)
        return await runtime.handle_user_turn(prompt, message_history=message_history)

    async def _execute_turn_core(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        skip_plan_execution: bool = True,
    ) -> str:
        _ = skip_plan_execution  # backward compatibility
        self._reload_model_from_db()

        self._previous_user_prompt = self._last_user_prompt
        self._last_user_prompt = prompt
        prompt = self._inject_task_notifications(prompt)
        prompt = self._inject_local_timestamp(prompt)
        user_content, _ = self._build_user_prompt_content(prompt)

        try:
            result = await self.agent.run(user_content, message_history=message_history)
            output_text = enforce_absolute_image_paths(result.output or "")
            try:
                self._last_messages = result.all_messages()
            except Exception:
                self._last_messages = None
            self._last_assistant_reply = self._extract_user_reply(output_text)
            return output_text
        except Exception as e:
            error_msg = str(e)
            logger.warning("Tool execution error in agent.run(): %s", error_msg)

            error_context = (
                f"\n\nTool execution error:\n{error_msg}\n\n"
                "Please provide a helpful response to the user explaining that the external service "
                "is temporarily unavailable and suggest alternatives if possible."
            )

            try:
                user_content_with_error = self._append_error_to_user_content(
                    user_content, error_context
                )
                result = await self.agent.run(
                    user_content_with_error, message_history=message_history
                )
                output_text = enforce_absolute_image_paths(result.output or "")
                try:
                    self._last_messages = result.all_messages()
                except Exception:
                    self._last_messages = None
                self._last_assistant_reply = self._extract_user_reply(output_text)
                return output_text
            except Exception as final_error:
                logger.error("All retry attempts failed: %s", final_error)
                final_prompt = (
                    f"The user asked: {self._last_user_prompt}\n\n"
                    f"A tool execution error occurred: {error_msg}\n"
                    "The external service is currently unavailable. "
                    "Please provide a helpful and friendly response to the user."
                )
                try:
                    result = await self.agent.run(final_prompt)
                    return enforce_absolute_image_paths(
                        result.output or "抱歉，目前無法連接到外部服務。請稍後再試。"
                    )
                except Exception:
                    return "抱歉，系統暫時無法處理您的請求。請稍後再試。"

    async def run_stream(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        skip_plan_execution: bool = True,
    ):
        from internal.app.handle_user_turn import create_runtime

        _ = skip_plan_execution  # backward compatibility
        runtime = create_runtime(self)
        async for chunk in runtime.handle_user_turn_stream(prompt, message_history=message_history):
            yield chunk

    async def _execute_turn_stream_core(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        skip_plan_execution: bool = True,
    ):
        _ = skip_plan_execution  # backward compatibility
        self._reload_model_from_db()

        self._previous_user_prompt = self._last_user_prompt
        self._last_user_prompt = prompt
        prompt = self._inject_task_notifications(prompt)
        prompt = self._inject_local_timestamp(prompt)
        user_content, _ = self._build_user_prompt_content(prompt)

        try:
            async with self.agent.run_stream(
                user_prompt=user_content, message_history=message_history
            ) as result:
                collected = ""
                normalizer = ImagePathStreamNormalizer()
                try:
                    async for chunk in result.stream_text(delta=True):
                        if not chunk:
                            continue
                        normalized_chunk = normalizer.feed(chunk)
                        if normalized_chunk:
                            collected += normalized_chunk
                            yield normalized_chunk
                    tail = normalizer.flush()
                    if tail:
                        collected += tail
                        yield tail
                except Exception as stream_error:
                    error_msg = str(stream_error)
                    logger.warning("Tool execution error during streaming: %s", error_msg)
                    yield (
                        f"\n\n[System Note: A tool execution error occurred: {error_msg}. "
                        "Please provide a helpful response explaining the service is temporarily unavailable.]"
                    )

                try:
                    self._last_messages = result.all_messages()
                except Exception:
                    self._last_messages = None
                self._last_assistant_reply = self._extract_user_reply(collected)
        except Exception as e:
            error_msg = str(e)
            logger.warning("Error in agent.run_stream(): %s", error_msg)

            error_context = (
                f"\n\nTool execution error:\n{error_msg}\n\n"
                "Please provide a helpful response to the user explaining that the external service "
                "is temporarily unavailable and suggest alternatives if possible."
            )
            try:
                user_content_with_error = self._append_error_to_user_content(
                    user_content, error_context
                )
                async with self.agent.run_stream(
                    user_prompt=user_content_with_error, message_history=message_history
                ) as result:
                    collected = ""
                    normalizer = ImagePathStreamNormalizer()
                    async for chunk in result.stream_text(delta=True):
                        if not chunk:
                            continue
                        normalized_chunk = normalizer.feed(chunk)
                        if normalized_chunk:
                            collected += normalized_chunk
                            yield normalized_chunk
                    tail = normalizer.flush()
                    if tail:
                        collected += tail
                        yield tail
                    try:
                        self._last_messages = result.all_messages()
                    except Exception:
                        self._last_messages = None
                    self._last_assistant_reply = self._extract_user_reply(collected)
            except Exception:
                yield "抱歉，系統暫時無法處理您的請求。請稍後再試。"
