import functools
import inspect
import json
import re
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
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
from internal.compaction import estimate_tokens, get_message_text, serialize_compaction_input
from internal.core.orchestration.runtime import OrchestrationRuntime
from internal.core.orchestration.store import OrchestrationStore
from internal.core.orchestration.types import (
    RecoveryPolicy as OrchestrationRecoveryPolicy,
    StepContract as OrchestrationStepContract,
    StepExecutionResult,
    StepSpec,
    TaskGraphPlan,
    VerificationEvidenceItem,
    VerificationReport,
)
from internal.core.protocol.image_output_paths import (
    ImagePathStreamNormalizer,
    enforce_absolute_image_paths,
)
from internal.core.protocol.verdict_parser import parse_verification_verdict

PROMPT_KEY = "MAIN_AGENT_PROMPT"
ENV_PREFIX = "MAIN"
REQUEST_CONTEXT_TOKEN_BUDGET = 900000
OVERFLOW_RETRY_KEEP_MESSAGES = 24


class MainAgent:
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX
    _IMAGE_DIRECTIVE_RE = re.compile(r"(?mi)^\s*(?:image|img)\s*:\s*(?P<target>.+?)\s*$")
    _IMAGE_MARKDOWN_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
    _TODO_ALLOWED_PHASES = frozenset({"planning", "executing", "blocked", "completed"})
    _TODO_ALLOWED_STATUSES = frozenset({"pending", "in_progress", "completed", "blocked"})
    _TODO_FORBIDDEN_TITLES = frozenset({"todo", "task", "step", "item"})

    @staticmethod
    def _build_subagent_report_contract(subagent_type: str) -> str:
        return (
            f"You are subagent '{subagent_type}'. Complete the assigned work, then report in this exact section order:\n"
            "[RESULT]\n"
            "- Concrete final result only (not future plans).\n"
            "[FILES_CHANGED]\n"
            "- One file path per line. Use '(none)' if no file changed.\n"
            "[COMMANDS]\n"
            "- One command per line, each prefixed with '$ '. Use '(none)' if not run.\n"
            "[EVIDENCE]\n"
            "- Essential outputs/findings that justify the result.\n"
            "[UNRESOLVED]\n"
            "- Remaining gaps/risks. Use '(none)' when fully complete.\n"
            "[NEEDED_INPUT]\n"
            "- Missing inputs required from coordinator/user. Use '(none)' if no dependency.\n"
            "Do not output only plan wording like 'I will/接下來'."
        )

    @staticmethod
    def _default_subagent_prompt() -> str:
        return (
            "You are a worker agent for the coding assistant system.\n\n"
            "Given the assigned task, use the tools available to complete the work fully.\n"
            "Do not over-engineer, but do not leave the task half-done.\n\n"
            "When you finish, respond with a concise report that includes:\n"
            "- what you did\n"
            "- key findings\n"
            "- any important limitations or follow-up notes\n\n"
            "The coordinator will relay the final answer to the user, so your response should focus on essentials."
        )

    @staticmethod
    def _subagent_env_notes() -> str:
        return (
            "Notes:\n"
            "- Agent execution environments may reset cwd between shell calls, so prefer absolute file paths.\n"
            "- In your final response, include only file paths that are directly relevant to the task.\n"
            "- Include code snippets only when the exact text is essential.\n"
            "- Do not recap large amounts of code you merely read.\n"
            "- Do not use emojis.\n"
            "- Do not write a colon immediately before a tool call."
        )

    @staticmethod
    def _built_in_subagent_prompt(agent_type: str) -> str:
        normalized = (agent_type or "").strip().lower()
        if normalized == "verification":
            return (
                "You are a verification-only worker.\n\n"
                "This task is for verification, not implementation.\n"
                "You must not edit, write, or create files in the project directory.\n"
                "Temporary files outside the project may be used only when strictly necessary for testing.\n\n"
                "For each important check, report:\n"
                "- what you verified\n"
                "- the exact command run\n"
                "- the observed output\n"
                "- whether it passed or failed\n\n"
                "You must end with exactly one of:\n"
                "VERDICT: PASS\n"
                "VERDICT: FAIL\n"
                "VERDICT: PARTIAL"
            )
        if normalized == "explore":
            return (
                "You are a file and code exploration specialist.\n"
                "This is a READ-ONLY task. Do not create, modify, or delete files.\n"
                "Use efficient searches first, then targeted reads, and return findings plus uncertainties."
            )
        if normalized == "plan":
            return (
                "You are a software architecture and implementation planning specialist.\n"
                "This is a READ-ONLY task. You must not create, edit, or delete files.\n"
                "Return a practical step-by-step plan with risks, trade-offs, and critical files."
            )
        return (
            "You are a general-purpose worker agent for the coding assistant system.\n"
            "Complete the assigned task using available tools. Be thorough, avoid over-engineering, and do not leave work half-done."
        )

    @classmethod
    def _build_subagent_system_prompt(
        cls,
        *,
        agent_type: str,
        append_prompt: str | None = None,
        include_env_notes: bool = True,
    ) -> str:
        base = cls._built_in_subagent_prompt(agent_type) or cls._default_subagent_prompt()
        env_notes = cls._subagent_env_notes() if include_env_notes else ""
        pieces = [base, env_notes, (append_prompt or "").strip()]
        return "\n\n".join(piece for piece in pieces if piece)

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
            main_agent._register_todo_tools()
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
        self._todo_tool_snapshot: str = ""
        self._todo_tool_items: list[dict[str, Any]] = []
        self._active_todo_update_callback: Callable[[str], None] | None = None
        self._task_manager = SubagentTaskManager(
            worker=self._run_subagent_task,
            enqueue_notification=self._enqueue_pending_notification,
        )
        # Orchestration v2 stays disabled on the main hot path until it is
        # redesigned to match the lighter ref_docs coordinator/todo model.
        self._orchestration_store: OrchestrationStore | None = None
        self._orchestration_runtime: OrchestrationRuntime | None = None
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
            created = await self._task_manager.spawnAgentTask(payload, self._session_id)
            if run_in_background:
                return cast(dict[str, str], created)

            task_id = created.get("task_id", "")
            task = self._task_manager.registry.getTask(task_id) if task_id else None
            if task is None:
                return cast(dict[str, str], created)

            return {
                "task_id": task.id,
                "status": task.status,
                "name": task.name or "",
                "summary": task.summary or "",
                "result": task.result or "",
                "files_changed": "\n".join(task.filesChanged),
                "commands_executed": "\n".join(task.commandsExecuted),
                "evidence": "\n".join(task.evidence),
                "unresolved_issues": "\n".join(task.unresolvedIssues),
            }

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

    def _render_todo_snapshot(self, phase: str, items: list[dict[str, Any]]) -> str:
        lines = [f"[TODO] phase={phase or 'executing'}"]
        if not items:
            lines.append("- (empty)")
            return "\n".join(lines)

        for raw in items:
            todo_id = str(raw.get("id", "")).strip() or "todo"
            title = str(raw.get("title", "")).strip() or str(raw.get("description", "")).strip() or todo_id
            status = str(raw.get("status", "")).strip() or "pending"
            notes = str(raw.get("notes", "")).strip()
            suffix = f" | notes={notes}" if notes else ""
            lines.append(f"- {todo_id} [{status}] {title}{suffix}")
        return "\n".join(lines)

    def _normalize_todo_payload(
        self,
        phase: str,
        items: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        normalized_phase = str(phase or "").strip().lower()
        if normalized_phase not in self._TODO_ALLOWED_PHASES:
            allowed = ", ".join(sorted(self._TODO_ALLOWED_PHASES))
            raise ValueError(f"todo.phase must be one of: {allowed}")

        normalized_items: list[dict[str, Any]] = []
        for index, raw in enumerate(items[:8], start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"todo.items[{index}] must be an object")

            todo_id = str(raw.get("id", "")).strip()
            title = str(raw.get("title", "")).strip()
            description = str(raw.get("description", "")).strip()
            status = str(raw.get("status", "")).strip().lower() or "pending"
            notes = str(raw.get("notes", "")).strip()

            if not todo_id:
                raise ValueError(f"todo.items[{index}].id is required")
            if not title:
                raise ValueError(f"todo.items[{index}].title is required")
            if title.strip().lower() in self._TODO_FORBIDDEN_TITLES:
                raise ValueError(
                    f"todo.items[{index}].title must be a concrete step, not '{title}'"
                )
            if status not in self._TODO_ALLOWED_STATUSES:
                allowed = ", ".join(sorted(self._TODO_ALLOWED_STATUSES))
                raise ValueError(
                    f"todo.items[{index}].status must be one of: {allowed}"
                )

            normalized_items.append(
                {
                    "id": todo_id,
                    "title": title,
                    "description": description,
                    "status": status,
                    "notes": notes,
                }
            )

        in_progress_count = sum(
            1 for item in normalized_items if item.get("status") == "in_progress"
        )
        if in_progress_count > 1:
            raise ValueError("todo list can have at most one in_progress item")

        return normalized_phase, normalized_items

    def _publish_todo_snapshot(
        self,
        snapshot: str,
        items: list[dict[str, Any]] | None = None,
        *,
        emit: bool = True,
    ) -> str:
        self._todo_tool_snapshot = (snapshot or "").strip()
        self._todo_tool_items = list(items or [])
        callback = self._active_todo_update_callback
        if emit and callback and self._todo_tool_snapshot:
            callback(self._todo_tool_snapshot)
        return self._todo_tool_snapshot

    def _register_todo_tools(self) -> None:
        @self.agent.tool_plain
        def todo(
            phase: str,
            items: list[dict[str, Any]],
        ) -> str:
            """Update the current session todo list with strict validation for phase, id, title, and status."""
            normalized_phase, normalized_items = self._normalize_todo_payload(
                phase,
                items,
            )
            snapshot = self._render_todo_snapshot(normalized_phase, normalized_items)
            return self._publish_todo_snapshot(snapshot, normalized_items)

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

    def _inject_todo_snapshot(self, prompt: str) -> str:
        guidance = (
            "<active-session-todos>\n"
            "Use the `todo` tool whenever the task has more than one distinct step — use your judgment on what counts as a step.\n"
            "Skip it only for truly trivial one-shot responses (e.g. a factual question, a single-line fix).\n"
            "Break the task into as many items as naturally fit — no minimum, no maximum. Each item should be the smallest unit of work you can confidently track and complete independently.\n"
            "Good breakdowns: granular enough to show progress, coarse enough to avoid noise. Avoid wrapping the entire request in one item.\n"
            "Each item must have a concrete, action-oriented title that describes what you will actually do, not what the user asked.\n"
            "Never use vague placeholder titles like 'todo', 'task', 'step', or 'item'.\n"
            "Allowed phases: planning, executing, blocked, completed.\n"
            "Allowed statuses: pending, in_progress, blocked, completed.\n"
            "Mark items in_progress as you work on them (at most one at a time), and completed as soon as they are done.\n"
            "Use `AgentTool` to delegate a step when parallel or specialized subagent execution helps.\n"
        )
        if self._todo_tool_snapshot:
            return (
                f"{guidance}\n"
                "Current todo snapshot:\n"
                f"{self._todo_tool_snapshot}\n"
                "</active-session-todos>\n\n"
                f"{prompt}"
            )
        return (
            f"{guidance}"
            "Current todo snapshot:\n"
            "- (empty)\n"
            "</active-session-todos>\n\n"
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
            if subagent_type not in {"compaction", "verification"}:
                worker_instructions = (
                    f"{(worker_instructions or '').strip()}\n\n"
                    f"{self._subagent_env_notes()}\n\n"
                    f"{self._build_subagent_report_contract(subagent_type)}"
                ).strip()
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
                worker_system_prompt = self._build_subagent_system_prompt(
                    agent_type=subagent_type,
                    include_env_notes=True,
                )
                worker_instructions = self._build_subagent_report_contract(subagent_type)

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

    def resume_incomplete_runs(self) -> list[str]:
        if self._orchestration_store is None:
            return []
        return self._orchestration_store.resume_incomplete_runs()

    @property
    def orchestration_store(self) -> OrchestrationStore | None:
        return self._orchestration_store

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

    def _estimate_user_content_tokens(self, user_content: list[UserContent]) -> int:
        total = 0
        for part in user_content:
            if isinstance(part, str):
                total += estimate_tokens(part)
            else:
                # Non-text content (image/url/binary) still consumes request budget.
                total += 512
        return total

    def _trim_message_history_for_budget(
        self,
        message_history: list[ModelRequest | ModelResponse] | None,
        user_content: list[UserContent],
    ) -> list[ModelRequest | ModelResponse] | None:
        if not message_history:
            return message_history

        prompt_tokens = self._estimate_user_content_tokens(user_content)
        budget_for_history = max(0, REQUEST_CONTEXT_TOKEN_BUDGET - prompt_tokens)

        kept: list[ModelRequest | ModelResponse] = []
        used = 0
        for msg in reversed(message_history):
            msg_tokens = estimate_tokens(get_message_text(msg))
            if kept and (used + msg_tokens) > budget_for_history:
                break
            kept.append(msg)
            used += msg_tokens

        trimmed = list(reversed(kept))
        dropped = len(message_history) - len(trimmed)
        if dropped > 0:
            logger.warning(
                "Trimmed message_history for context budget: dropped=%s kept=%s prompt_tokens=%s budget_for_history=%s",
                dropped,
                len(trimmed),
                prompt_tokens,
                budget_for_history,
            )
        return trimmed

    def _is_context_overflow_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        markers = [
            "maximum context length",
            "context length",
            "too many tokens",
            "requested about",
            "token limit",
        ]
        return any(marker in text for marker in markers)

    def _overflow_retry_history(
        self,
        message_history: list[ModelRequest | ModelResponse] | None,
    ) -> list[ModelRequest | ModelResponse] | None:
        if not message_history:
            return message_history
        if len(message_history) <= OVERFLOW_RETRY_KEEP_MESSAGES:
            return message_history
        trimmed = message_history[-OVERFLOW_RETRY_KEEP_MESSAGES:]
        logger.warning(
            "Context overflow retry using reduced history: original=%s kept=%s",
            len(message_history),
            len(trimmed),
        )
        return trimmed

    async def _follow_through_needs_retry(self, user_prompt: str, output_text: str) -> bool:
        if not output_text.strip():
            return True
        if not self._http_client:
            return False

        verification_task = SimpleNamespace(subagentType="verification", mode="spawn")
        verification_prompt = (
            "You are validating whether the assistant actually delivered requested work in this turn.\n"
            "Return exactly one verdict line: VERDICT: PASS / VERDICT: FAIL / VERDICT: PARTIAL.\n"
            "PASS: concrete deliverables/results are present.\n"
            "FAIL: mostly promises/plans without concrete results.\n"
            "PARTIAL: some output exists but request is not adequately completed.\n\n"
            "USER REQUEST:\n"
            f"{user_prompt}\n\n"
            "ASSISTANT OUTPUT:\n"
            f"{output_text}\n"
        )

        try:
            verification_output = await self._run_subagent_task(verification_task, verification_prompt)
            verdict = parse_verification_verdict(
                verification_output,
                task_id="follow-through-check",
            ).verdict
            return verdict in {"FAIL", "PARTIAL"}
        except Exception as exc:
            logger.warning("Follow-through verification unavailable, skip retry: %s", exc)
            return False

    def _build_follow_through_retry_context(self) -> str:
        return (
            "\n\nValidation Guard:\n"
            "The previous response appears not fully delivered for this turn.\n"
            "Continue immediately and provide concrete completion output now.\n"
            "Do not provide only future-plan wording.\n"
        )

    @staticmethod
    def _orchestration_default_contract(goal: str) -> OrchestrationStepContract:
        return OrchestrationStepContract(
            doneWhen=goal,
            mustProduce=["summary"],
            mustNotChange=[],
            requiredChecks=[],
            evidenceShape=["summary"],
            repairHint="narrow the failing scope and preserve prior successful checks",
        )

    @staticmethod
    def _orchestration_default_recovery_policy() -> OrchestrationRecoveryPolicy:
        return OrchestrationRecoveryPolicy(
            maxAttempts=2,
            onTransient="retry-step",
            onDeterministic="create-repair-step",
            onDependency="wait-dependency",
            onUserDecision="wait-user",
            onSystemCrash="resume-from-checkpoint",
        )

    @staticmethod
    def _orchestration_step_kind_for_task(task_kind: str) -> str:
        return "implement" if task_kind in {"implementation", "bugfix", "infra"} else "discover"

    def _orchestration_parse_plan_json(
        self,
        raw: str,
        task_kind: str,
        user_request: str,
    ) -> TaskGraphPlan:
        fallback_kind = self._orchestration_step_kind_for_task(task_kind)
        try:
            payload = json.loads((raw or "").strip())
        except Exception:
            payload = {}

        if isinstance(payload, list):
            payload = {"steps": payload}
        steps_payload = payload.get("steps") if isinstance(payload, dict) else None
        steps: list[StepSpec] = []
        if isinstance(steps_payload, list):
            for index, item in enumerate(steps_payload, start=1):
                if not isinstance(item, dict):
                    continue
                step_id = str(item.get("step_id") or item.get("stepId") or f"step_{index:03d}").strip()
                kind = str(item.get("kind") or fallback_kind).strip().lower()
                if kind not in {"discover", "plan", "implement", "verify", "repair", "synthesize", "ask_user"}:
                    kind = fallback_kind
                goal = str(item.get("goal") or item.get("title") or user_request).strip() or user_request
                depends_on_raw = item.get("depends_on") or item.get("dependsOn") or []
                depends_on = [str(dep).strip() for dep in depends_on_raw] if isinstance(depends_on_raw, list) else []
                inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
                inputs = {"user_request": user_request, **inputs}
                contract_payload = item.get("contract") if isinstance(item.get("contract"), dict) else {}
                contract = OrchestrationStepContract(
                    doneWhen=str(contract_payload.get("done_when") or contract_payload.get("doneWhen") or goal),
                    mustProduce=list(contract_payload.get("must_produce") or contract_payload.get("mustProduce") or ["summary"]),
                    mustNotChange=list(contract_payload.get("must_not_change") or contract_payload.get("mustNotChange") or []),
                    requiredChecks=list(contract_payload.get("required_checks") or contract_payload.get("requiredChecks") or []),
                    evidenceShape=list(contract_payload.get("evidence_shape") or contract_payload.get("evidenceShape") or ["summary"]),
                    repairHint=str(contract_payload.get("repair_hint") or contract_payload.get("repairHint") or "retry with narrowed scope"),
                )
                retry_payload = item.get("retry_policy") if isinstance(item.get("retry_policy"), dict) else item.get("retryPolicy")
                retry_payload = retry_payload if isinstance(retry_payload, dict) else {}
                steps.append(
                    StepSpec(
                        stepId=step_id,
                        kind=cast(Any, kind),
                        goal=goal,
                        dependsOn=depends_on,
                        executor=str(item.get("executor") or "worker"),
                        inputs=inputs,
                        contract=contract,
                        verificationMode=str(item.get("verification_mode") or item.get("verificationMode") or "none"),
                        retryPolicy=OrchestrationRecoveryPolicy(
                            maxAttempts=int(retry_payload.get("max_attempts") or retry_payload.get("maxAttempts") or 2),
                            onTransient=str(retry_payload.get("on_transient") or retry_payload.get("onTransient") or "retry-step"),
                            onDeterministic=str(retry_payload.get("on_deterministic") or retry_payload.get("onDeterministic") or "create-repair-step"),
                            onDependency=str(retry_payload.get("on_dependency") or retry_payload.get("onDependency") or "wait-dependency"),
                            onUserDecision=str(retry_payload.get("on_user_decision") or retry_payload.get("onUserDecision") or "wait-user"),
                            onSystemCrash=str(retry_payload.get("on_system_crash") or retry_payload.get("onSystemCrash") or "resume-from-checkpoint"),
                        ),
                        recoveryPoint=str(item.get("recovery_point") or item.get("recoveryPoint") or f"checkpoint:{step_id}"),
                    )
                )

        if not steps:
            steps = [
                StepSpec(
                    stepId="step_001",
                    kind=cast(Any, fallback_kind),
                    goal=user_request,
                    executor="worker",
                    inputs={"user_request": user_request},
                    contract=self._orchestration_default_contract(user_request),
                    verificationMode="independent" if task_kind in {"implementation", "bugfix", "infra"} else "none",
                    retryPolicy=self._orchestration_default_recovery_policy(),
                    recoveryPoint="checkpoint:step_001",
                )
            ]
        return TaskGraphPlan(taskKind=cast(Any, task_kind), steps=steps)

    async def _orchestration_build_task_graph(self, task_kind: str, user_request: str) -> TaskGraphPlan:
        execute_turn = getattr(self, "_execute_turn_core", None)
        if not callable(execute_turn):
            return self._orchestration_parse_plan_json("", task_kind, user_request)
        planner_prompt = (
            "You are the Task Graph Planner for a durable orchestration engine.\n"
            "Return JSON only with shape: {\"steps\": [...]}.\n"
            "Each step must include: step_id, kind, goal, depends_on, executor, inputs, contract, verification_mode, retry_policy, recovery_point.\n"
            "Allowed kinds: discover, plan, implement, verify, repair, synthesize, ask_user.\n"
            "Rules:\n"
            "- use at most 5 steps\n"
            "- implementation, bugfix, infra must include verify after implement\n"
            "- synthesize should depend on all user-visible work being done\n"
            "- keep inputs minimal and task-scoped\n"
            "- do not include markdown fences\n\n"
            f"Task kind: {task_kind}\n"
            f"User request:\n{user_request}"
        )
        try:
            raw = await execute_turn(planner_prompt)
        except Exception:
            raw = ""
        return self._orchestration_parse_plan_json(raw, task_kind, user_request)

    async def coordinator_handle_user_turn(
        self,
        user_prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        on_todo_update: Callable[[str], None] | None = None,
    ) -> str:
        def todo_callback(snapshot: str) -> None:
            self._publish_todo_snapshot(snapshot, self._todo_tool_items, emit=False)
            if on_todo_update:
                on_todo_update(snapshot)

        self._active_todo_update_callback = todo_callback
        try:
            execute_turn = getattr(self, "_execute_turn_core", None)
            if not callable(execute_turn):
                raise RuntimeError("Main agent execution core is unavailable")
            return await execute_turn(
                user_prompt,
                message_history=message_history,
                skip_plan_execution=True,
            )
        finally:
            self._active_todo_update_callback = None

    async def coordinator_handle_user_turn_stream(
        self,
        user_prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        on_todo_update: Callable[[str], None] | None = None,
    ) -> AsyncIterator[str]:
        result = await self.coordinator_handle_user_turn(
            user_prompt,
            message_history=message_history,
            on_todo_update=on_todo_update,
        )
        if result:
            yield result

    async def _orchestration_execute_step(
        self,
        step: StepSpec,
        upstream_artifacts: list[dict[str, Any]],
    ) -> StepExecutionResult:
        if step.kind == "synthesize":
            for artifact in reversed(upstream_artifacts):
                candidate = str(artifact.get("result") or artifact.get("summary") or "").strip()
                if candidate:
                    return StepExecutionResult(
                        status="completed",
                        summary=step.goal,
                        result=candidate,
                        evidence=[candidate],
                    )
            return StepExecutionResult(status="completed", summary=step.goal, result=step.goal)

        subagent_type = "implementation" if step.kind in {"implement", "repair"} else "research"
        prompt_sections = [
            f"STEP KIND: {step.kind}",
            f"STEP GOAL: {step.goal}",
            f"DONE WHEN: {step.contract.doneWhen}",
            "USER REQUEST:\n" + str(step.inputs.get("user_request", step.goal)),
        ]
        if step.contract.requiredChecks:
            prompt_sections.append("REQUIRED CHECKS:\n" + "\n".join(step.contract.requiredChecks))
        if upstream_artifacts:
            prompt_sections.append("UPSTREAM ARTIFACTS:\n" + json.dumps(upstream_artifacts, ensure_ascii=False))
        output = await self._run_subagent_task(
            SimpleNamespace(subagentType=subagent_type, mode="spawn"),
            "\n\n".join(prompt_sections),
        )
        worker_result = self._task_manager._build_worker_result(  # noqa: SLF001
            step.stepId,
            output,
            __import__("time").time(),
        )
        failed = bool(worker_result.unresolvedIssues)
        return StepExecutionResult(
            status=cast(Any, "failed" if failed else "completed"),
            summary=worker_result.summary,
            result=worker_result.result,
            filesChanged=worker_result.filesChanged,
            commandsExecuted=worker_result.commandsExecuted,
            evidence=worker_result.evidence,
            unresolvedIssues=worker_result.unresolvedIssues,
            failureClass=cast(Any, "deterministic") if failed else None,
        )

    async def _orchestration_execute_verification(
        self,
        step: StepSpec,
        upstream_artifacts: list[dict[str, Any]],
    ) -> VerificationReport:
        original_request = str(step.inputs.get("user_request", step.goal))
        claims = upstream_artifacts[-1] if upstream_artifacts else {}
        output = await self._run_subagent_task(
            SimpleNamespace(subagentType="verification", mode="spawn"),
            (
                "ORIGINAL USER REQUEST:\n"
                f"{original_request}\n\n"
                "STEP CONTRACT:\n"
                f"{json.dumps({'done_when': step.contract.doneWhen, 'required_checks': step.contract.requiredChecks}, ensure_ascii=False)}\n\n"
                "UPSTREAM ARTIFACTS:\n"
                f"{json.dumps(upstream_artifacts, ensure_ascii=False)}\n\n"
                "CLAIMS TO VERIFY:\n"
                f"{json.dumps(claims, ensure_ascii=False)}"
            ),
        )
        verdict = parse_verification_verdict(output, task_id=step.stepId)
        remediation_steps = [
            StepSpec(
                stepId=todo.id,
                kind="repair",
                goal=todo.description or todo.title,
                dependsOn=list(dict.fromkeys(step.dependsOn)),
                executor="worker",
                inputs={"user_request": original_request, "verification_feedback": todo.description or todo.title},
                contract=self._orchestration_default_contract(todo.description or todo.title),
                verificationMode="independent",
                retryPolicy=self._orchestration_default_recovery_policy(),
                recoveryPoint=f"{step.recoveryPoint}:repair:{todo.id}",
            )
            for todo in verdict.remediationTodos
        ]
        return VerificationReport(
            verdict=cast(Any, verdict.verdict),
            summary=verdict.summary,
            checkedItems=[e.command for e in verdict.evidence if e.command],
            failedItems=[*verdict.missingRequirements, *verdict.suspectedProblems],
            evidence=[
                VerificationEvidenceItem(
                    name=e.command or "check",
                    result=e.result,
                    detail=e.output,
                )
                for e in verdict.evidence
            ],
            remediationSteps=remediation_steps,
            confidence=1.0 if verdict.verdict == "PASS" else 0.5,
            requiresUserInput=False,
        )

    async def run(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        skip_plan_execution: bool = True,
    ) -> str:
        _ = skip_plan_execution  # backward compatibility
        return await self.coordinator_handle_user_turn(
            prompt,
            message_history=message_history,
        )

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
        prompt = self._inject_todo_snapshot(prompt)
        prompt = self._inject_local_timestamp(prompt)
        user_content, _ = self._build_user_prompt_content(prompt)
        safe_history = self._trim_message_history_for_budget(message_history, user_content)

        try:
            result = await self.agent.run(user_content, message_history=safe_history)
            output_text = enforce_absolute_image_paths(result.output or "")
            try:
                self._last_messages = result.all_messages()
            except Exception:
                self._last_messages = None
            self._last_assistant_reply = self._extract_user_reply(output_text)

            return output_text
        except Exception as e:
            if self._is_context_overflow_error(e):
                retry_history = self._overflow_retry_history(safe_history)
                if retry_history is not safe_history:
                    try:
                        result = await self.agent.run(user_content, message_history=retry_history)
                        output_text = enforce_absolute_image_paths(result.output or "")
                        try:
                            self._last_messages = result.all_messages()
                        except Exception:
                            self._last_messages = None
                        self._last_assistant_reply = self._extract_user_reply(output_text)
                        return output_text
                    except Exception as retry_exc:
                        e = retry_exc

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
                    user_content_with_error, message_history=safe_history
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
        _ = skip_plan_execution  # backward compatibility
        async for chunk in self.coordinator_handle_user_turn_stream(
            prompt,
            message_history=message_history,
        ):
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
        prompt = self._inject_todo_snapshot(prompt)
        prompt = self._inject_local_timestamp(prompt)
        user_content, _ = self._build_user_prompt_content(prompt)
        safe_history = self._trim_message_history_for_budget(message_history, user_content)

        try:
            async with self.agent.run_stream(
                user_prompt=user_content, message_history=safe_history
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
            if self._is_context_overflow_error(e):
                retry_history = self._overflow_retry_history(safe_history)
                if retry_history is not safe_history:
                    try:
                        async with self.agent.run_stream(
                            user_prompt=user_content, message_history=retry_history
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
                            return
                    except Exception as retry_exc:
                        e = retry_exc

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
                    user_prompt=user_content_with_error, message_history=safe_history
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
