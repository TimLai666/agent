import asyncio
import functools
import inspect
import json
import re
import sys
from typing import Any, cast

from httpx import AsyncClient
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.co_agents.philosopher import PhilosopherCoAgent
from internal.logger import logger
from internal.prompts import (
    SYSTEM_PROMPT,
    build_runtime_instructions,
    get_prompt,
    load_keyword_triggers,
    load_subagent_background_config,
)
from internal.services.agent_factory import (
    AgentConfig,
    create_openai_model,
    load_agent_config_chain,
)
from internal.set_tools import add_all_tools
from internal.skills_loader import SkillRegistry, load_skill_registry
from internal.sub_agents import SubAgentRegistry, load_sub_agent_registry

from internal.mcp_server_list import all_mcp_servers

PROMPT_KEY = "MAIN_AGENT_PROMPT"
ENV_PREFIX = "MAIN"


def _plan_is_empty(plan_obj: dict) -> bool:
    plan = plan_obj.get("execution_plan")
    if plan is None:
        plan = plan_obj.get("plan")
    if plan is None:
        plan = plan_obj.get("steps")
    if plan is None:
        plan = plan_obj
    return isinstance(plan, list) and len(plan) == 0


class MainAgent:
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX
    TOOL_RECOVERY_MAX_ATTEMPTS = 2

    @classmethod
    def create(
        cls,
        base_config: AgentConfig,
        env: dict[str, str],
        http_client: AsyncClient,
        philosopher: PhilosopherCoAgent,
        sub_agents: SubAgentRegistry | None = None,
        skills: SkillRegistry | None = None,
    ) -> "MainAgent":
        # Load skills first (so sub-agents can use them)
        if skills is None:
            try:
                skills = load_skill_registry()
            except Exception:
                logger.exception("Failed to load skills; continuing without them")
                skills = SkillRegistry({}, None)

        # Load sub-agents with skills
        if sub_agents is None:
            try:
                sub_agents = cast(
                    SubAgentRegistry,
                    load_sub_agent_registry(
                        base_config,
                        env,
                        http_client,
                        philosopher=philosopher,
                        skills=skills,
                    ),
                )
            except Exception:
                logger.exception("Failed to load sub-agents; continuing without them")
                sub_agents = SubAgentRegistry({}, {})

        # Apply MAIN-specific default temperature of 0.5 when MAIN_MODEL_TEMPERATURE is not set.
        main_defaults = AgentConfig(
            name="main",
            base_url=base_config.base_url,
            api_key=base_config.api_key,
            model_name=base_config.model_name,
            temperature=0.5,
        )
        config = load_agent_config_chain([cls.ENV_PREFIX], main_defaults, env)
        model = create_openai_model(config, http_client)
        instructions = build_runtime_instructions(get_prompt(cls.PROMPT_KEY))
        if sub_agents and not sub_agents.is_empty():
            instructions += "\n\nSub-agents are available via tools: list_sub_agents, ask_sub_agent."
   
        mcp_servers = all_mcp_servers

        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=instructions,
            tools=[],
            model_settings={"temperature": config.temperature},
            toolsets=mcp_servers,
        )

        planner_agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=(
                "你是嚴格的 JSON 轉換器。"
                "只負責把主 agent 給你的工具請求轉成 JSON，"
                "不要自行決定工具或新增步驟。"
            ),
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        discussion_agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=(
                "You are the main agent in an internal discussion with the philosopher. "
                "Provide a concise candidate answer for the user and respond to critique. "
                "Do not call tools. Do not include self-validation."
            ),
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        # Lightweight decider agent: same underlying model, but no system prompt, no tools, no MCP/toolsets
        decider_agent: Agent[None, str] = Agent(
            model=model,
            system_prompt="",
            instructions="",
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        # Register skill tool (Claude Code compatible)
        from internal.tools.skill_tools import register_skill_tool

        register_skill_tool(agent, skills)

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
                            return res
                        except Exception:
                            logger.exception(
                                "Tool %s raised an exception", func.__name__
                            )
                            raise

                    wrapped_callable = wrapped_async
                else:

                    @functools.wraps(func)
                    def wrapped_sync(*args, **kwargs):
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
                            return res
                        except Exception:
                            logger.exception(
                                "Tool %s raised an exception", func.__name__
                            )
                            raise

                    wrapped_callable = wrapped_sync

                # delegate to the original registration API with the wrapped callable
                return original_tool_plain(wrapped_callable, **kwargs)

            cast(Any, agent).tool_plain = logging_tool_plain

        main_agent = cls(
            agent,
            philosopher,
            sub_agents,
            planner_agent,
            discussion_agent,
            decider_agent,
            skills,
            http_client,
        )
        try:
            add_all_tools(
                agent,
                extra_tools=[
                    main_agent.ask_philosopher,
                    main_agent.list_sub_agents,
                    main_agent.ask_sub_agent,
                ],
            )
            if sub_agents and not sub_agents.is_empty():
                sub_agents.register_tools(agent)
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
        philosopher: PhilosopherCoAgent,
        sub_agents: SubAgentRegistry | None = None,
        planner_agent: Agent[None, str] | None = None,
        discussion_agent: Agent[None, str] | None = None,
        decider_agent: Agent[None, str] | None = None,
        skills: SkillRegistry | None = None,
        http_client: AsyncClient | None = None,
    ) -> None:
        self.agent = agent
        self.philosopher = philosopher
        self.sub_agents = sub_agents
        self.skills = skills
        self._planner_agent = planner_agent or agent
        self._discussion_agent = discussion_agent
        self._decider_agent = decider_agent or agent
        self._last_messages: list[ModelRequest | ModelResponse] | None = None
        self._last_execution_steps: list[dict[str, Any]] = []
        self._last_user_prompt: str | None = None
        self._previous_user_prompt: str | None = None
        self._last_assistant_reply: str | None = None
        self._mcp_tool_names: set[str] | None = None  # 緩存 MCP 工具名稱列表
        self._http_client = http_client  # 保存以便重載 model
        # tools are registered via add_all_tools during create()

    def _reload_model_from_db(self) -> None:
        """從資料庫重新載入配置並更新 model。
        
        每次 run() 或 run_stream() 時都會調用，確保使用最新的配置。
        """
        if not self._http_client:
            logger.warning("無法重載 model：沒有 http_client")
            return
        
        try:
            # 從資料庫載入最新配置
            config = AgentConfig(
                name="main",
                base_url=None,
                api_key=None,
                model_name="",
                temperature=0.5,
            )
            new_model = create_openai_model(config, self._http_client)
            
            # 更新所有 agent 的 model
            self.agent._model = new_model
            if self._planner_agent and self._planner_agent is not self.agent:
                self._planner_agent._model = new_model
            if self._discussion_agent and self._discussion_agent is not self.agent:
                self._discussion_agent._model = new_model
            if self._decider_agent and self._decider_agent is not self.agent:
                self._decider_agent._model = new_model
            
            logger.debug("已從資料庫重載 model 配置")
        except Exception:
            logger.exception("重載 model 配置失敗，繼續使用現有配置")

    async def _extract_execution_plan(self, text: str) -> dict | None:
        """Try to extract an execution plan JSON from free text.

        Expected forms:
        - A top-level JSON object containing key 'execution_plan' or 'plan'
        - A raw JSON object representing the plan
        Returns parsed dict or None.
        """
        if not text:
            return None
        # Try full-text JSON parse first
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and (
                "execution_plan" in parsed or "plan" in parsed
            ):
                return parsed
            # if the parsed dict itself *is* a plan
            if isinstance(parsed, dict) and (
                "steps" in parsed or "plan" in parsed or "execution_plan" in parsed
            ):
                return parsed
        except Exception:
            pass

        # Try to locate JSON substrings by scanning for balanced braces
        # This avoids naive first/last-brace substring matching which can
        # capture unrelated trailing text. We scan for each '{' and find the
        # matching '}' by counting depth, then try to json.loads() that slice.
        text_len = len(text)
        i = 0
        while i < text_len:
            if text[i] != "{":
                i += 1
                continue
            depth = 0
            j = i
            while j < text_len:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        snippet = text[i : j + 1]
                        try:
                            parsed = json.loads(snippet)
                            if isinstance(parsed, dict) and (
                                "execution_plan" in parsed
                                or "plan" in parsed
                                or "steps" in parsed
                            ):
                                return parsed
                        except Exception:
                            # ignore parse errors and continue scanning
                            pass
                        break
                j += 1
            # advance i to the next character after the current '{' to find other candidates
            i += 1

        return None

    async def execute_plan(
        self,
        plan_obj: dict,
        pre_steps_meta: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Execute an execution_plan-like object.

        plan_obj may contain 'execution_plan' or 'plan' or 'steps'. Each step should be
        an object with at least 'tool' and optional 'args' (dict) and 'note'.

        Returns a list of result messages (strings) for each step.
        """
        results: list[str] = []
        # normalize
        if "execution_plan" in plan_obj:
            plan = plan_obj.get("execution_plan")
        elif "plan" in plan_obj:
            plan = plan_obj.get("plan")
        elif "steps" in plan_obj:
            plan = plan_obj.get("steps")
        else:
            # maybe the plan_obj itself is the list
            plan = plan_obj

        if not isinstance(plan, list):
            return ["Plan format invalid: expected a list of steps."]

        step_outputs: list[str] = []
        steps_meta: list[dict[str, Any]] = []
        for idx, step in enumerate(plan):
            tool_name = step.get("tool") if isinstance(step, dict) else None
            args = step.get("args", {}) if isinstance(step, dict) else {}
            note = step.get("note") if isinstance(step, dict) else None
            header = f"Step {idx + 1}: {tool_name}"
            if note:
                header += f"  ({note})"
            results.append(header)
            step_meta: dict[str, Any] = {"tool": tool_name, "args": args, "note": note}

            registered = self._get_function_tools()
            allowed_names = set(registered.keys())

            attempts = 0
            current_tool = tool_name
            current_args = args
            current_error = ""
            while True:
                if isinstance(current_tool, str) and "ask_philosopher" in allowed_names:
                    if current_tool == "ask_philosopher":
                        question = ""
                        if isinstance(current_args, dict):
                            question = str(
                                current_args.get("question")
                                or current_args.get("prompt")
                                or ""
                            ).strip()
                        if not question:
                            question = self._build_sub_agent_prompt(
                                note, current_args, step_outputs
                            )
                        current_args = {
                            "question": self._build_philosopher_prompt(
                                note, current_args, step_outputs, question
                            )
                        }
                    elif current_tool in {"philosopher", "哲學家"}:
                        question = self._build_sub_agent_prompt(
                            note, current_args, step_outputs
                        )
                        current_tool = "ask_philosopher"
                        current_args = {
                            "question": self._build_philosopher_prompt(
                                note, current_args, step_outputs, question
                            )
                        }
                    elif current_tool == "ask_sub_agent":
                        name = ""
                        if isinstance(current_args, dict):
                            name = str(current_args.get("name", "")).strip().lower()
                        if name in {"philosopher", "哲學家", "philosopher-co-agent"}:
                            question = ""
                            if isinstance(current_args, dict):
                                question = str(current_args.get("prompt", "")).strip()
                            if not question:
                                question = self._build_sub_agent_prompt(
                                    note, current_args, step_outputs
                                )
                            current_tool = "ask_philosopher"
                            current_args = {
                                "question": self._build_philosopher_prompt(
                                    note, current_args, step_outputs, question
                                )
                            }

                if (
                    self.sub_agents
                    and isinstance(current_tool, str)
                    and self.sub_agents.get_agent(current_tool)
                    and "ask_sub_agent" in allowed_names
                ):
                    prompt = self._build_sub_agent_prompt(
                        note, current_args, step_outputs
                    )
                    current_args = {"name": current_tool, "prompt": prompt}
                    current_tool = "ask_sub_agent"

                if not current_tool:
                    current_error = "Missing 'tool' field."
                elif current_tool not in allowed_names:
                    # 檢查是否為 MCP 工具
                    if isinstance(current_tool, str) and self._is_mcp_tool(current_tool):
                        # MCP 工具的錯誤：記錄後跳出，不進入 recovery
                        # 這樣錯誤資訊會被傳遞給 LLM，由 LLM 生成友好的回應
                        step_meta["error"] = (
                            f"MCP tool '{current_tool}' cannot be executed in plan mode. "
                            "This tool requires agent runtime context."
                        )
                        results.append(f"  -> MCP tool error: {step_meta['error']}")
                        break  # 跳出 while True 循環，不進入 recovery
                    else:
                        current_error = f"Tool '{current_tool}' is not registered."
                
                if not current_error and current_tool in allowed_names:
                    
                    if current_args:
                        current_args = self._resolve_args(current_args, step_outputs)
                    if current_args is None:
                        current_args = {}
                    elif not isinstance(current_args, dict):
                        current_args = {"value": current_args}
                    tool_def = (
                        registered.get(str(current_tool))
                        if isinstance(current_tool, str)
                        else None
                    )
                    if tool_def is None:
                        current_error = f"Tool '{current_tool}' declared but not found on agent runtime."
                    elif getattr(tool_def, "takes_ctx", False):
                        current_error = f"Tool '{current_tool}' requires context and cannot be called directly."
                    else:
                        callable_obj = tool_def.function
                        try:
                            try:
                                schema = tool_def.function_schema.json_schema or {}
                                expected_keys = list(
                                    (schema.get("properties") or {}).keys()
                                )
                            except Exception:
                                expected_keys = []
                            if current_args and expected_keys:
                                expected_set = set(expected_keys)
                                if not set(current_args.keys()).issubset(expected_set):
                                    if (
                                        len(expected_keys) == 1
                                        and len(current_args) == 1
                                    ):
                                        current_args = {
                                            expected_keys[0]: next(
                                                iter(current_args.values())
                                            )
                                        }
                            if current_tool == "get_stock_history":
                                period = current_args.get("period")
                                if isinstance(period, str):
                                    normalized = period.lower()
                                    if normalized in {"month", "1m"}:
                                        current_args["period"] = "1mo"
                                    elif normalized in {"3m"}:
                                        current_args["period"] = "3mo"
                            logger.info(
                                "Executing tool '%s' with args: %s",
                                current_tool,
                                current_args,
                            )
                            if inspect.iscoroutinefunction(callable_obj):
                                res = await callable_obj(**current_args)
                            else:
                                maybe = (
                                    callable_obj(**current_args)
                                    if current_args
                                    else callable_obj()
                                )
                                if asyncio.iscoroutine(maybe):
                                    res = await maybe
                                else:
                                    res = maybe
                            logger.info(
                                "Tool '%s' execution result: %s", current_tool, res
                            )
                            results.append(f"  -> result: {res}")
                            step_outputs.append(str(res))
                            step_meta["result"] = res
                            step_meta["tool"] = current_tool
                            break
                        except Exception as e:
                            logger.exception("Error executing tool %s", current_tool)
                            current_error = f"Execution error: {e}"
                            step_meta["error"] = current_error

                if attempts >= self.TOOL_RECOVERY_MAX_ATTEMPTS:
                    if current_error:
                        results.append(f"  -> execution error: {current_error}")
                        step_meta["error"] = current_error
                    break

                attempts += 1
                results.append(f"  -> recovery attempt {attempts}: {current_error}")
                recovery = await self._recover_tool_call(
                    tool=current_tool,
                    args=current_args,
                    error=current_error,
                    note=note,
                )
                if not recovery:
                    results.append(
                        "  -> recovery failed: no corrected tool call returned"
                    )
                    step_meta["error"] = (
                        "recovery failed: no corrected tool call returned"
                    )
                    break
                current_tool = recovery.get("tool")
                current_args = recovery.get("args", {})

            steps_meta.append(step_meta)

        self._last_execution_steps = steps_meta
        return results

    async def _recover_tool_call(
        self,
        tool: str | None,
        args: dict[str, Any] | None,
        error: str,
        note: str | None,
    ) -> dict[str, Any] | None:
        tools_text: str = self._format_tools_context().strip()
        sub_agents_text = self._format_sub_agents_context().strip()
        note_text = f"Note: {note}\n" if note else ""
        prompt = (
            "工具呼叫失敗。你必須修正 tool 名稱與/或 args，並且只輸出 JSON。\n"
            "可使用 ask_sub_agent 協助。\n\n"
            f"{tools_text}\n"
            f"{sub_agents_text}\n"
            f"{note_text}"
            f"失敗的 tool：{tool}\n"
            f"args：{args}\n"
            f"錯誤：{error}\n\n"
            '只輸出 JSON，格式：{"tool": "tool_name", "args": {"key": "value"}}。\n'
            '如需使用前一步結果，可用 "$last" 或 "$step1" 佔位符。\n'
        )

        for attempt in range(2):
            try:
                retry_hint = ""
                if attempt == 1:
                    retry_hint = (
                        "上一次沒有輸出合法 JSON。這次只輸出 JSON，不能有其他文字。\n\n"
                    )
                result = await self._planner_agent.run(retry_hint + prompt)
                out = (result.output or "").strip()
                parsed = json.loads(out)
                if isinstance(parsed, dict) and parsed.get("tool"):
                    return {"tool": parsed.get("tool"), "args": parsed.get("args", {})}
            except Exception:
                logger.exception("Tool recovery failed")
        return None

    async def _should_consult_philosopher(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> bool:
        """以主 agent 模型決定是否需要與哲學家討論。

        會向 `decider` 發出簡短判定請求（回傳 YES/NO 與簡短原因）。
        若模型失敗或回應不明確，採保守策略：回傳 True 以確保討論。
        """
        # 使用嚴格 JSON 回應格式：{"consult": true|false, "reason": "..."}
        # 範例幫助模型學習何種問題需要討論（簡單事實性問題不需要）
        decider = (
            "你是主 agent 的決策助手。請判斷下列使用者輸入是否需要向哲學家 co-agent 進行多輪內省討論。"
            " 嚴格回傳一個有效 JSON 對象，不要包含其他文字。JSON 格式：{'consult': true/false, 'reason': '短理由'}。"
            " **重要**：在這個判定步驟中，請不要呼叫任何工具或嘗試執行外部函式；僅依靠你的語言理解回傳 JSON。"
            " 範例：\n"
            "輸入: '現在幾點'\n輸出: {"
            + '"consult": false, "reason": "簡單事實性查詢"}'
            + "\n"
            "輸入: '評估不同投資組合的風險與報酬'\n輸出: {"
            + '"consult": true, "reason": "需要權衡與推理"}'
            + "\n\n"
            "使用者輸入：\n" + prompt + "\n\n請只回傳 JSON，且不要呼叫任何工具："
        )

        try:
            dec = getattr(self, "_decider_agent", self.agent)
            result = await dec.run(decider, message_history=message_history)
            out = (result.output or "").strip()
            # 嘗試解析 JSON
            try:
                parsed = json.loads(out)
                consult = bool(parsed.get("consult", False))
                return consult
            except Exception:
                # 若模型回傳包含 JSON 片段，嘗試從其中抽取 true/false
                lower = out.lower()
                if (
                    "true" in lower
                    or "yes" in lower
                    or "是" in lower
                    or "需要" in lower
                ):
                    return True
                if (
                    "false" in lower
                    or "no" in lower
                    or "否" in lower
                    or "不需要" in lower
                ):
                    return False
                # 解析失敗：為避免多餘討論，採保守策略：不討論
                logger.info(
                    "Decision response not parseable; defaulting to NO consult. Response: %s",
                    out,
                )
                return False
        except Exception:
            logger.exception(
                "Decision call to main agent failed; defaulting to NO consult"
            )
            return False

    async def ask_philosopher(self, question: str) -> str:
        """Tool: forward question to philosopher co-agent."""
        if not self.philosopher:
            raise RuntimeError("Philosopher co-agent is not available.")
        return await self.philosopher.run(question)

    async def _run_philosopher_discussion(self, question: str) -> str:
        discussion: list[tuple[str, str]] = []
        max_rounds = 5
        main_draft: str | None = None
        discussion_agent = self._discussion_agent or self.agent
        initial_prompt = self._build_main_discussion_prompt(None, None)
        main_result = await discussion_agent.run(initial_prompt)
        main_draft = (main_result.output or "").strip()
        discussion.append(("MainAgent", main_draft))

        for _ in range(max_rounds):
            phil_prompt = self._build_philosopher_prompt(
                note=None,
                args=None,
                step_outputs=None,
                question=question,
                main_draft=main_draft,
            )
            phil_output = await self.philosopher.run(phil_prompt)
            discussion.append(("Philosopher", phil_output))

            main_prompt = self._build_main_discussion_prompt(phil_output, main_draft)
            main_result = await discussion_agent.run(main_prompt)
            main_draft = (main_result.output or "").strip()
            discussion.append(("MainAgent", main_draft))

            phil_agrees = self._parse_philosopher_agreement(phil_output)
            if phil_agrees is True and await self._should_end_discussion(
                discussion, last_main_answer=main_draft
            ):
                break

        return "\n".join(f"{speaker}: {text}" for speaker, text in discussion)

    async def _run_philosopher_discussion_stream(self, question: str):
        discussion: list[tuple[str, str]] = []
        max_rounds = 5
        main_draft: str | None = None
        discussion_agent = self._discussion_agent or self.agent
        initial_prompt = self._build_main_discussion_prompt(None, None)
        main_result = await discussion_agent.run(initial_prompt)
        main_draft = (main_result.output or "").strip()
        discussion.append(("MainAgent", main_draft))
        yield f"MainAgent: {main_draft}"

        for _ in range(max_rounds):
            phil_prompt = self._build_philosopher_prompt(
                note=None,
                args=None,
                step_outputs=None,
                question=question,
                main_draft=main_draft,
            )
            phil_output = await self.philosopher.run(phil_prompt)
            discussion.append(("Philosopher", phil_output))
            yield f"Philosopher: {phil_output}"

            main_prompt = self._build_main_discussion_prompt(phil_output, main_draft)
            main_result = await discussion_agent.run(main_prompt)
            main_draft = (main_result.output or "").strip()
            discussion.append(("MainAgent", main_draft))
            yield f"MainAgent: {main_draft}"

            phil_agrees = self._parse_philosopher_agreement(phil_output)
            if phil_agrees is True and await self._should_end_discussion(
                discussion, last_main_answer=main_draft
            ):
                break

    def list_sub_agents(self) -> list[dict[str, str]]:
        """Tool: list available sub-agents (name + short description)."""
        if not self.sub_agents:
            return []
        return self.sub_agents.list_summaries()

    async def ask_sub_agent(self, name: str = "", prompt: str = "", **kwargs) -> str:
        """Tool: delegate a task to a sub-agent by name.

        Args:
            name: Name of the sub-agent to use
            prompt: The task or question for the sub-agent
            **kwargs: Additional arguments (ignored for compatibility)

        Returns:
            The sub-agent's response
        """
        if not name:
            return "Error: 'name' argument is required for ask_sub_agent."
        if not prompt:
            return "Error: 'prompt' argument is required for ask_sub_agent."

        # Ignore extra kwargs (e.g., 'role') for compatibility
        if kwargs:
            logger.debug(
                f"ask_sub_agent ignoring extra arguments: {list(kwargs.keys())}"
            )

        if not self.sub_agents or self.sub_agents.is_empty():
            return "No sub-agents are registered."

        agent = self.sub_agents.get_agent(name)
        if not agent:
            available = ", ".join(self.sub_agents.list_names())
            return f"Unknown sub-agent '{name}'. Available: {available}"

        if hasattr(agent, "run_stream"):
            collected = ""
            async for chunk in agent.run_stream(prompt):
                collected += chunk
            return collected
        return await agent.run(prompt)

    def _format_sub_agents_context(self) -> str:
        if not self.sub_agents or self.sub_agents.is_empty():
            return "Available sub-agents: (none)\n\n"
        lines = ["Available sub-agents:"]
        for spec in self.sub_agents.list_specs():
            desc = spec.short_description()
            if desc:
                lines.append(f"- {spec.name}: {desc}")
            else:
                lines.append(f"- {spec.name}")
        return "\n".join(lines) + "\n\n"

    def _format_tools_context(self) -> str:
        """格式化所有可用工具的說明，包含直接註冊的工具和 MCP Server。"""
        lines = []
        
        # 1. 直接註冊的工具
        tools_meta = self._get_function_tools()
        if tools_meta:
            lines.append("Available tools:")
            for name, tool in tools_meta.items():
                doc = tool.description.splitlines()[0] if tool.description else ""
                params = []
                try:
                    schema = tool.function_schema.json_schema or {}
                    params = list((schema.get("properties") or {}).keys())
                except Exception:
                    params = []
                sig = f"({', '.join(params)})" if params else "()"
                if doc:
                    lines.append(f"- {name}{sig}: {doc}")
                else:
                    lines.append(f"- {name}{sig}")
        else:
            lines.append("Available tools: (none)")
        
        # 2. MCP Servers（在運行時由 pydantic-ai 動態處理）
        mcp_servers = self._get_mcp_servers()
        if mcp_servers:
            lines.append("\nMCP Servers (tools available at runtime):")
            for server in mcp_servers:
                prefix = getattr(server, 'tool_prefix', None) or 'no-prefix'
                command = getattr(server, 'command', 'unknown')
                args = getattr(server, 'args', [])
                server_name = f"{command} {' '.join(args) if args else ''}".strip()
                if prefix != 'no-prefix':
                    lines.append(f"- {prefix}_* (from {server_name})")
                else:
                    lines.append(f"- MCP Server: {server_name}")
        
        return "\n".join(lines) + "\n\n"

    def _get_function_tools(self) -> dict[str, Any]:
        """取得所有可用工具，包含直接註冊的工具和 MCP 工具。
        
        注意：這個方法返回的是已經註冊到 agent 的工具。
        MCP 工具只有在 run_mcp_servers() context 內且 LLM 實際調用時才會被動態解析。
        """
        all_tools = {}
        
        # 1. 取得直接註冊的工具
        tools_meta = getattr(self.agent, "_function_tools", None)
        if tools_meta:
            all_tools.update(tools_meta)
        
        # 2. 取得 toolset 中的工具
        toolset = getattr(self.agent, "_function_toolset", None)
        if toolset and getattr(toolset, "tools", None):
            all_tools.update(toolset.tools)
        
        return all_tools
    
    def _get_mcp_servers(self) -> list:
        """取得所有 MCP Server 實例。"""
        user_toolsets = getattr(self.agent, "_user_toolsets", [])
        from pydantic_ai.mcp import MCPServerStdio
        return [ts for ts in user_toolsets if isinstance(ts, MCPServerStdio)]
    
    def _try_get_mcp_tool_names(self) -> set[str] | None:
        """嘗試獲取所有 MCP 工具的名稱列表。
        
        注意：只有在 MCP Server 已經啟動並初始化後才能獲取工具列表。
        如果無法獲取（例如 server 未啟動），返回 None。
        """
        mcp_servers = self._get_mcp_servers()
        if not mcp_servers:
            return None
        
        tool_names = set()
        for server in mcp_servers:
            # 檢查 server 是否已經運行
            is_running = getattr(server, 'is_running', False)
            if not is_running:
                # Server 未運行，無法獲取工具列表
                continue
            
            try:
                # pydantic-ai 的 MCPServerStdio 有 _cached_tools 屬性
                # 在 server 連接後會緩存工具列表
                cached_tools = getattr(server, '_cached_tools', None)
                if cached_tools and isinstance(cached_tools, list):
                    # 從緩存的工具列表中提取名稱
                    for tool in cached_tools:
                        # 工具可能是 dict 或對象
                        if isinstance(tool, dict):
                            name = tool.get('name')
                        else:
                            name = getattr(tool, 'name', None)
                        if name:
                            tool_names.add(name)
            except Exception:
                # 忽略錯誤，繼續處理下一個 server
                pass
        
        return tool_names if tool_names else None
    
    def _is_mcp_tool(self, tool_name: str) -> bool:
        """檢查是否為 MCP 工具。
        
        從 MCP Server 的 _cached_tools 獲取實際的工具列表進行比對。
        """
        # 如果有緩存，直接使用
        if self._mcp_tool_names is not None:
            return tool_name in self._mcp_tool_names
        
        # 嘗試從 MCP Server 獲取工具列表
        mcp_tool_names = self._try_get_mcp_tool_names()
        if mcp_tool_names:
            self._mcp_tool_names = mcp_tool_names
            return tool_name in mcp_tool_names
        
        # 無法獲取工具列表
        return False

    def _get_recent_tool_output(self) -> str | None:
        for step in reversed(self._last_execution_steps):
            if step.get("tool") == "get_now":
                continue
            if "result" in step:
                return str(step["result"])
        return None

    def _extract_current_time(self) -> str | None:
        for step in self._last_execution_steps:
            if step.get("tool") == "get_now" and "result" in step:
                return str(step["result"])
        return None

    def _build_sub_agent_prompt(
        self,
        note: str | None,
        args: dict[str, Any] | None,
        step_outputs: list[str] | None = None,
    ) -> str:
        if args:
            for key in ("prompt", "question", "task", "input"):
                value = args.get(key)
                if value:
                    return str(value)
        parts: list[str] = []
        if self._last_user_prompt:
            parts.append(self._last_user_prompt)
        if note:
            parts.append(f"Note: {note}")
        if step_outputs:
            parts.append(f"Latest tool output: {step_outputs[-1]}")
        else:
            recent_output = self._get_recent_tool_output()
            if recent_output:
                parts.append(f"Previous tool output: {recent_output}")
        if parts:
            return "\n\n".join(parts)
        return "Please handle this step."

    def _extract_user_reply(self, output: str | None) -> str | None:
        if not output:
            return None
        text = output
        if "<self-validation>" in text:
            text = text.split("<self-validation>", 1)[0]
        return text.strip() or None

    def _build_philosopher_prompt(
        self,
        note: str | None,
        args: dict[str, Any] | None,
        step_outputs: list[str] | None,
        question: str | None,
        main_draft: str | None = None,
    ) -> str:
        parts = [
            "You are the philosopher co-agent in an internal discussion with the main agent.",
            "Provide reasoning and context the main agent can use to answer the user.",
            "Do NOT ask the user questions. Answer directly based on context.",
            "End with a line: Agreement: yes/no.",
        ]
        if self._previous_user_prompt:
            parts.append(f"Previous user message: {self._previous_user_prompt}")
        if self._last_assistant_reply:
            parts.append(f"Previous assistant reply: {self._last_assistant_reply}")
        if self._last_user_prompt:
            parts.append(f"Current user message: {self._last_user_prompt}")
        if note:
            parts.append(f"Plan note: {note}")
        if question:
            parts.append(f"Question: {question}")
        if main_draft:
            parts.append(f"Main agent draft response: {main_draft}")
        if step_outputs:
            parts.append(f"Latest tool output: {step_outputs[-1]}")
        else:
            recent_output = self._get_recent_tool_output()
            if recent_output:
                parts.append(f"Previous tool output: {recent_output}")
        return "\n\n".join(parts)

    def _parse_philosopher_agreement(self, text: str | None) -> bool | None:
        if not text:
            return None
        lowered = text.lower()
        if "agreement:" in lowered:
            for line in lowered.splitlines():
                if "agreement:" in line:
                    if "yes" in line:
                        return True
                    if "no" in line:
                        return False
        if "同意" in text:
            return True
        if "不同意" in text or "不認同" in text:
            return False
        return None

    def _build_main_discussion_prompt(
        self,
        phil_output: str | None,
        main_draft: str | None,
    ) -> str:
        prompt = (
            "You are the main agent in an internal discussion with the philosopher.\n"
            "Respond to the philosopher's points and draft a concise answer for the user.\n"
            "Do not call tools. Do not include self-validation. Do not ask the user questions.\n\n"
        )
        if self._previous_user_prompt:
            prompt += f"Previous user message: {self._previous_user_prompt}\n\n"
        if self._last_assistant_reply:
            prompt += f"Previous assistant reply: {self._last_assistant_reply}\n\n"
        if self._last_user_prompt:
            prompt += f"Current user message: {self._last_user_prompt}\n\n"
        if main_draft:
            prompt += f"Previous draft: {main_draft}\n\n"
        if phil_output:
            prompt += f"Philosopher feedback:\n{phil_output}\n\n"
        prompt += "Provide the updated draft answer only."
        return prompt

    def _resolve_args(self, args: Any, step_outputs: list[str]) -> Any:
        def resolve_value(value: Any) -> Any:
            if isinstance(value, str):
                if value == "$last" and step_outputs:
                    return step_outputs[-1]
                if value.startswith("$step"):
                    try:
                        idx = int(value[5:]) - 1
                        if 0 <= idx < len(step_outputs):
                            return step_outputs[idx]
                    except ValueError:
                        return value
                return value
            if isinstance(value, list):
                return [resolve_value(item) for item in value]
            if isinstance(value, dict):
                return {key: resolve_value(val) for key, val in value.items()}
            return value

        return resolve_value(args)

    async def _request_execution_plan(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        attempt: int = 1,
        force_tools: bool = False,
    ) -> dict | None:
        draft = await self._draft_tool_requests(
            prompt, message_history=message_history, force_tools=force_tools
        )
        if not draft:
            return None

        retry_hint = ""
        if attempt > 1:
            retry_hint = (
                "你上一次沒有輸出合法 JSON。這次只能輸出 JSON。\n"
                "不得新增或刪除主 agent 的工具步驟。\n\n"
            )

        plan_prompt = (
            '你只能把下列工具請求轉成 JSON，格式固定為 {"plan": [ ... ]}。\n'
            "不得自行決定工具、不得新增/刪除步驟、不得更改參數語意。\n"
            "每個步驟必須包含 tool 欄位；需要參數時加入 args 物件，沒有參數就省略或用 {}。\n"
            '若請求為 none，回傳 {"plan": []}。\n'
            "忽略 INTENT，只轉換 TOOL_REQUESTS。\n"
            "只輸出 JSON。\n\n"
            + retry_hint
            + "主 agent 說明與工具請求：\n"
            + draft
            + "\n\n只輸出 JSON。"
        )

        try:
            result = await self._planner_agent.run(plan_prompt)
            out = (result.output or "").strip()
            logger.info("Planner output (attempt %s): %s", attempt, out)
            return await self._extract_execution_plan(out)
        except Exception:
            logger.exception("Failed to request execution plan")
            return None

    async def _draft_tool_requests(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        force_tools: bool = False,
    ) -> str:
        tools_text = self._format_tools_context()
        sub_agents_text = self._format_sub_agents_context()
        force_hint = ""
        if force_tools:
            force_hint = (
                "這是一個強制工具評估回合：若任何工具/子代?能提升準確性或避免猜測，"
                "必須輸出 TOOL_REQUESTS，不可輸出 none。\n"
                "若完全不需要工具（可直接回答且無需查證/執行），才可輸出 TOOL_REQUESTS: none。\n\n"
            )
        draft_prompt = (
            force_hint
            + "你是主 agent 的規劃器。先寫一段話描述你要做什麼、怎麼做，然後列出工具請求。\n"
            "輸出格式只允許下列兩種之一：\n"
            "1) INTENT: <一段話>\n"
            "   TOOL_REQUESTS: none\n"
            "2) INTENT: <一段話>\n"
            "   TOOL_REQUESTS:\n"
            "   - tool: tool_name\n"
            '     args: {"key": "value"}\n'
            "每一步都必須明確指定 tool；無參數就省略 args 行。\n"
            '如果後續步驟需要前一步的輸出，使用 "$last" 或 "$step1" 佔位符。\n'
            "不得輸出 JSON。\n\n"
            "重要：如果需求涉及時事/最新/新聞/趨勢，必須列出瀏覽器/MCP 工具或請求 trend-researcher；不可憑空編造。\n"
            "若無法取得可靠來源，工具請求應為 none，並在 INTENT 指出需要使用者指定具體事件。\n\n"
            "常見需求對應工具（若符合就直接用）：\n"
            "- 查某日期是星期幾：get_weekday，參數 date_str\n"
            "- 擲骰子：roll_dice\n"
            "- 從清單隨機挑一個：random_pick，參數 items\n"
            "- 目前工作目錄：get_current_directory\n"
            "- 列出目錄檔案：list_files_in_directory，參數 dir\n"
            "- 讀取檔案內容：read_file，參數 file_path\n"
            "- 作業系統/架構：get_platform_info\n"
            "- 股價/股史：get_current_stock_price 或 get_stock_history\n"
            "  - ticker_symbol 請使用使用者原始市場代碼（例如 AAPL、TSLA、7203.T、2330.TW）\n"
            "  - 台股如無後綴，請在 args 補上 2330.TW 或提供 is_taiwan_stock=true\n\n"
            + tools_text
            + sub_agents_text
            + f"使用者需求：\n{prompt}\n\n"
            "只輸出工具請求清單。"
        )

        try:
            result = await self.agent.run(draft_prompt, message_history=message_history)
            out = (result.output or "").strip()
            logger.info("Draft tool requests: %s", out)
            return out
        except Exception:
            logger.exception("Failed to draft tool requests")
            return ""

    async def _should_force_tool_use(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> bool:
        """Ask the main agent if a tool call is required to avoid guessing."""
        decider = (
            "你是工具使用判斷器。判斷此問題是否需要工具才能可靠回答。\n"
            "若需要查檔案/執行命令/外部查證/多步推理驗證，force 應為 true。\n"
            "若可直接回答且不需查證，force 為 false。\n"
            '只輸出 JSON：{"force": true|false, "reason": "..."}\n\n'
            f"使用者請求：\n{prompt}\n"
        )
        try:
            res = await self.agent.run(decider, message_history=message_history)
            out = (res.output or "").strip()
            parsed = json.loads(out)
            return bool(parsed.get("force", False))
        except Exception:
            return False

    async def _build_plan_list(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> list[dict[str, Any] | Any]:
        plan_obj = await self._request_execution_plan(
            prompt, message_history=message_history, attempt=1
        )
        if plan_obj is None or _plan_is_empty(plan_obj):
            plan_obj = await self._request_execution_plan(
                prompt, message_history=message_history, attempt=2
            )
        if plan_obj is None or _plan_is_empty(plan_obj):
            if await self._should_force_tool_use(
                prompt, message_history=message_history
            ):
                plan_obj = await self._request_execution_plan(
                    prompt,
                    message_history=message_history,
                    attempt=3,
                    force_tools=True,
                )

        plan_list: list[dict[str, Any]] | list[Any]
        if isinstance(plan_obj, dict):
            if "execution_plan" in plan_obj:
                plan_list = plan_obj.get("execution_plan") or []
            elif "plan" in plan_obj:
                plan_list = plan_obj.get("plan") or []
            elif "steps" in plan_obj:
                plan_list = plan_obj.get("steps") or []
            else:
                plan_list = plan_obj if isinstance(plan_obj, list) else []
        elif isinstance(plan_obj, list):
            plan_list = plan_obj
        else:
            plan_list = []

        if not isinstance(plan_list, list):
            plan_list = []

        return plan_list

    def _prepare_prompt(self, prompt: str) -> tuple[str, list[str]]:
        if not prompt or not self.sub_agents or self.sub_agents.is_empty():
            return prompt, []
        tools_meta = self._get_function_tools()
        if "ask_sub_agent" not in tools_meta:
            return prompt, []
        return self.sub_agents.extract_mentions(prompt)

    def _strip_code_blocks(self, text: str) -> str:
        if not text:
            return text
        text = re.sub(r"```[\s\S]*?```", "", text)
        return re.sub(r"`[^`]+`", "", text)

    def _apply_keyword_triggers(self, prompt: str) -> tuple[str, dict[str, Any]]:
        triggers = load_keyword_triggers()
        if not triggers or not prompt:
            return prompt, {"names": [], "background": False}
        cleaned = self._strip_code_blocks(prompt)
        matched: list[str] = []
        prefix_blocks: list[str] = []
        suffix_blocks: list[str] = []
        background_enabled = False
        for trigger in triggers:
            pattern = str(trigger.get("pattern", ""))
            try:
                regex = re.compile(pattern)
            except re.error:
                continue
            if not regex.search(cleaned):
                continue
            name = str(trigger.get("name", "keyword"))
            inject = str(trigger.get("inject", ""))
            if not inject:
                continue
            if trigger.get("background") is True:
                background_enabled = True
            block = f"[keyword:{name}]\n{inject}"
            if trigger.get("position") == "suffix":
                suffix_blocks.append(block)
            else:
                prefix_blocks.append(block)
            matched.append(name)
        if prefix_blocks:
            prompt = "\n\n".join(prefix_blocks) + "\n\n" + prompt
        if suffix_blocks:
            prompt = prompt + "\n\n" + "\n\n".join(suffix_blocks)
        return prompt, {"names": matched, "background": background_enabled}

    def _plan_requests_subagent(self, plan_list: list[dict[str, Any] | Any]) -> bool:
        if not self.sub_agents or self.sub_agents.is_empty():
            return False
        for step in plan_list:
            if not isinstance(step, dict):
                continue
            tool_name = step.get("tool")
            if tool_name == "ask_sub_agent":
                return True
            if isinstance(tool_name, str) and self.sub_agents.resolve_name(tool_name):
                return True
        return False

    def _filter_plan_subagent_steps(
        self,
        plan_list: list[dict[str, Any] | Any],
        names: list[str],
    ) -> list[dict[str, Any] | Any]:
        if not names or not self.sub_agents or self.sub_agents.is_empty():
            return plan_list
        normalized = {self.sub_agents.resolve_name(name) for name in names}
        normalized = {name for name in normalized if name}
        if not normalized:
            return plan_list
        filtered: list[dict[str, Any] | Any] = []
        for step in plan_list:
            if not isinstance(step, dict):
                filtered.append(step)
                continue
            tool_name = step.get("tool")
            if tool_name == "ask_sub_agent":
                target = ""
                if isinstance(step.get("args"), dict):
                    target = str(step.get("args", {}).get("name", "")).strip()
                resolved = self.sub_agents.resolve_name(target) if target else None
                if resolved and resolved in normalized:
                    continue
            if isinstance(tool_name, str):
                resolved = self.sub_agents.resolve_name(tool_name)
                if resolved and resolved in normalized:
                    continue
            filtered.append(step)
        return filtered

    async def _decide_sub_agents(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> list[str]:
        if not prompt or not self.sub_agents or self.sub_agents.is_empty():
            return []
        tools_meta = self._get_function_tools()
        if "ask_sub_agent" not in tools_meta:
            return []

        summaries = self.sub_agents.list_summaries()
        if not summaries:
            return []

        candidates = "\n".join(
            f"- {item['name']}: {item['description']}"
            if item.get("description")
            else f"- {item['name']}"
            for item in summaries
        )

        config = load_subagent_background_config()
        max_auto_agents = int(config.get("max_auto_agents", 2))
        decision_prompt = (
            "你是主 agent 的子代理選擇器。根據使用者需求，從清單挑選最合適的子代理。\n"
            "若沒有明確需要，回傳空陣列。\n"
            '只回傳 JSON：{"agents": ["name1", "name2"]}。\n'
            f"最多選 {max_auto_agents} 個，必須是清單中的名稱，不要輸出其他文字。\n\n"
            "可用子代理：\n"
            f"{candidates}\n\n"
            "使用者需求：\n"
            f"{prompt}\n"
        )

        try:
            result = await self.agent.run(
                decision_prompt, message_history=message_history
            )
            out = (result.output or "").strip()
            parsed = json.loads(out)
            agents = parsed.get("agents", [])
            if not isinstance(agents, list):
                return []
            normalized = []
            for name in agents:
                if not isinstance(name, str):
                    continue
                resolved = self.sub_agents.resolve_name(name)
                if resolved and resolved not in normalized:
                    normalized.append(resolved)
            return normalized[:max_auto_agents]
        except Exception:
            return []

    def _resolve_background_mode(self, trigger_state: dict[str, Any]) -> bool:
        config = load_subagent_background_config()
        if config.get("background_always") is True:
            return True
        if config.get("background_on_trigger") is False:
            return False
        return bool(trigger_state.get("background"))

    def _get_subagent_concurrency(self) -> int:
        config = load_subagent_background_config()
        value = config.get("max_concurrency", 3)
        if isinstance(value, int):
            return max(1, value)
        return 3

    async def _run_subagent_with_semaphore(
        self,
        name: str,
        prompt: str,
        semaphore: asyncio.Semaphore,
    ) -> str:
        async with semaphore:
            return await self.ask_sub_agent(name, prompt)

    def _start_subagent_tasks(
        self,
        names: list[str],
        prompt: str,
    ) -> tuple[list[str], list[asyncio.Task]]:
        if not names or not self.sub_agents or self.sub_agents.is_empty():
            return [], []
        max_concurrency = self._get_subagent_concurrency()
        semaphore = asyncio.Semaphore(max_concurrency)
        order: list[str] = []
        tasks: list[asyncio.Task] = []
        for name in names:
            resolved = self.sub_agents.resolve_name(name)
            if not resolved:
                continue
            order.append(resolved)
            tasks.append(
                asyncio.create_task(
                    self._run_subagent_with_semaphore(resolved, prompt, semaphore)
                )
            )
        return order, tasks

    async def _collect_subagent_results(
        self,
        order: list[str],
        tasks: list[asyncio.Task],
        prompt: str,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        if not order or not tasks:
            return [], []
        results = await asyncio.gather(*tasks, return_exceptions=True)
        output_lines: list[str] = []
        steps_meta: list[dict[str, Any]] = []
        for name, result in zip(order, results):
            header = f"Parallel sub-agent: {name}"
            output_lines.append(header)
            step_meta: dict[str, Any] = {
                "tool": "ask_sub_agent",
                "args": {"name": name, "prompt": prompt},
            }
            if isinstance(result, Exception):
                error_text = f"Execution error: {result}"
                output_lines.append(f"  -> execution error: {error_text}")
                step_meta["error"] = error_text
            else:
                output_lines.append(f"  -> result: {result}")
                step_meta["result"] = result
            steps_meta.append(step_meta)
        return output_lines, steps_meta

    async def _should_end_discussion(
        self,
        discussion: list[tuple[str, str]],
        last_main_answer: str | None = None,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> bool:
        """Ask the main agent model whether the discussion can end.

        Returns True if the main agent judges the discussion sufficient to form
        a final answer. Expects a strict JSON reply: {"end": true|false, "reason": "..."}.
        Falls back to keyword checks on philosopher critique when parsing fails.
        """
        # Build a short prompt summarizing the discussion and candidate answer
        summary = """請判斷下列討論與主 agent 的候選回答是否已足以得出最終答案。只有在哲學家明確同意（Agreement: yes/同意）時才能結束。只回傳 JSON：{" + '"end": true/false, "reason": "短理由"}' + "，不要其他文字。\n\n討論摘要：\n"""
        for speaker, text in discussion:
            summary += f"{speaker}: {text}\n"
        if last_main_answer:
            summary += f"\n主 agent 候選回答：\n{last_main_answer}\n"

        summary += "\n**重要**：不要呼叫任何工具。只依據討論判斷並回傳 JSON。"

        decider = self._discussion_agent or self.agent
        try:
            res = await decider.run(summary, message_history=message_history)
            out = (res.output or "").strip()
            try:
                parsed = json.loads(out)
                return bool(parsed.get("end", False))
            except Exception:
                # 尝试基于可解析的文字作简单判定；若无法解析则不结束
                lower = out.lower()
                if (
                    "true" in lower
                    or "yes" in lower
                    or "可以" in lower
                    or "結束" in lower
                ):
                    return True
                if (
                    "false" in lower
                    or "no" in lower
                    or "不" in lower
                    or "還需要" in lower
                ):
                    return False
                # 解析失敗：不回退、不使用任何後備規則，直接回傳 False（繼續討論）
                return False
        except Exception:
            logger.exception(
                "End-discussion decision call failed; defaulting to NO end"
            )
            return False

    async def _decide_discussion_depth(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> dict:
        """Ask the main agent model what discussion depth to use.
        Returns a dict like {"depth": "very_shallow"|"shallow"|"medium"|"deep"|"very_deep", "rounds": 1..5}.
        On parse failure or exception, return {'depth':'medium','rounds':2}.
        """
        dec = (
            "你是主 agent 的討論深度決策器。請根據下列使用者問題判斷哲學家討論的內容深度（very_shallow/shallow/medium/deep/very_deep），"
            ' 並回傳嚴格的 JSON：{"depth": "very_shallow|shallow|medium|deep|very_deep", "rounds": 1..5}.'
            ' 範例：\n輸入：\'現在幾點\'\n輸出：{"depth": "very_shallow", "rounds": 1}\n'
            '輸入：\'評估不同投資組合的風險與報酬\'\n輸出：{"depth": "very_deep", "rounds": 5}\n\n使用者輸入：\n'
            + prompt
            + "\n\n請只回傳 JSON，且不要呼叫工具。"
        )

        try:
            res = await self.agent.run(dec, message_history=message_history)
            out = (res.output or "").strip()
            try:
                parsed = json.loads(out)
                depth = parsed.get("depth", "medium")
                rounds = int(parsed.get("rounds", 2))
                if depth not in (
                    "very_shallow",
                    "shallow",
                    "medium",
                    "deep",
                    "very_deep",
                ):
                    depth = "medium"
                if rounds < 1:
                    rounds = 1
                if rounds > 5:
                    rounds = 5
                return {"depth": depth, "rounds": rounds}
            except Exception:
                return {"depth": "medium", "rounds": 2}
        except Exception:
            logger.exception("Discussion depth decision failed; defaulting to medium")
            return {"depth": "medium", "rounds": 2}

    async def run(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        skip_plan_execution: bool = True,  # 默認跳過 plan execution，讓 agent 自己調用工具
    ) -> str:
        # 每次執行前從資料庫重載配置
        self._reload_model_from_db()
        
        self._previous_user_prompt = self._last_user_prompt
        self._last_user_prompt = prompt
        prompt, explicit_subagents = self._prepare_prompt(prompt)
        prompt, trigger_state = self._apply_keyword_triggers(prompt)

        # 如果啟用 skip_plan_execution，直接讓 agent.run() 自己調用工具
        if skip_plan_execution:
            # 只處理 sub-agents（如果需要）
            auto_subagents = (
                []
                if explicit_subagents
                else await self._decide_sub_agents(prompt, message_history=message_history)
            )
            parallel_subagents = explicit_subagents or auto_subagents
            
            if parallel_subagents:
                order, tasks = self._start_subagent_tasks(parallel_subagents, prompt)
                if order and tasks:
                    parallel_results, parallel_meta = await self._collect_subagent_results(
                        order, tasks, prompt
                    )
                    self._last_execution_steps = parallel_meta
                    if parallel_results:
                        exec_text = "\n".join(parallel_results)
                        prompt = f"{prompt}\n\nSub-agent results:\n{exec_text}"
            
            # 直接調用 agent.run()，捕獲 MCP 工具錯誤
            try:
                result = await self.agent.run(prompt, message_history=message_history)
                try:
                    self._last_messages = result.all_messages()
                except Exception:
                    self._last_messages = None
                self._last_assistant_reply = self._extract_user_reply(result.output or "")
                return result.output or ""
            except Exception as e:
                # 捕獲 MCP 工具錯誤，將錯誤資訊附加到 prompt 中，讓 LLM 生成友好的回應
                error_msg = str(e)
                logger.warning(f"Tool execution error in agent.run(): {error_msg}")
                
                # 將錯誤作為執行結果附加到 prompt
                error_context = (
                    f"\n\nTool execution error:\n{error_msg}\n\n"
                    "Please provide a helpful response to the user explaining that the external service "
                    "is temporarily unavailable and suggest alternatives if possible."
                )
                
                # 重新調用 agent.run()，這次不呼叫工具，只是讓 LLM 看到錯誤並生成回應
                try:
                    result = await self.agent.run(prompt + error_context, message_history=message_history)
                    try:
                        self._last_messages = result.all_messages()
                    except Exception:
                        self._last_messages = None
                    self._last_assistant_reply = self._extract_user_reply(result.output or "")
                    return result.output or ""
                except Exception as final_error:
                    # 最後的 fallback - 建立簡單的錯誤說明讓 agent 理解
                    logger.error(f"All retry attempts failed: {final_error}")
                    final_prompt = (
                        f"The user asked: {self._last_user_prompt}\n\n"
                        f"A tool execution error occurred: {error_msg}\n"
                        "The external service is currently unavailable. "
                        "Please provide a helpful and friendly response to the user."
                    )
                    # 最後一次嘗試，不帶歷史記錄，簡單調用
                    try:
                        result = await self.agent.run(final_prompt)
                        return result.output or "抱歉，目前無法連接到外部服務。請稍後再試。"
                    except Exception:
                        # 真的完全失敗了，返回基本訊息
                        return "抱歉，系統暫時無法處理您的請求。請稍後再試。"

        # 舊的 plan execution 模式（保留以備需要）
        # Skills are now tool-based (use_skill tool) - no automatic injection
        plan_list = await self._build_plan_list(prompt, message_history=message_history)
        if explicit_subagents:
            plan_list = self._filter_plan_subagent_steps(plan_list, explicit_subagents)
        has_subagent_in_plan = self._plan_requests_subagent(plan_list)
        auto_subagents = (
            []
            if explicit_subagents or has_subagent_in_plan
            else await self._decide_sub_agents(prompt, message_history=message_history)
        )
        parallel_subagents = explicit_subagents or auto_subagents
        background_mode = self._resolve_background_mode(trigger_state)
        exec_results: list[str] = []
        parallel_results: list[str] = []
        parallel_meta: list[dict[str, Any]] = []
        order, tasks = self._start_subagent_tasks(parallel_subagents, prompt)
        # Present plan as suggestions rather than forcing tool execution.
        # This allows the LLM to consider the plan and choose whether to call tools itself.
        if order and tasks:
            parallel_results, parallel_meta = await self._collect_subagent_results(
                order, tasks, prompt
            )
            if parallel_results:
                exec_results.extend(parallel_results)
        plan_meta: list[dict[str, Any]] = []
        if plan_list:
            suggested_lines: list[str] = []
            for idx, step in enumerate(plan_list, start=1):
                tool_name = step.get("tool") if isinstance(step, dict) else None
                args = step.get("args", {}) if isinstance(step, dict) else {}
                note = step.get("note") if isinstance(step, dict) else None
                header = f"Suggested Step {idx}: {tool_name}"
                if note:
                    header += f"  ({note})"
                args_text = ""
                if args:
                    try:
                        args_text = f" args: {json.dumps(args, ensure_ascii=False)}"
                    except Exception:
                        args_text = f" args: {str(args)}"
                line = header + args_text
                suggested_lines.append(line)
                plan_meta.append({"tool": tool_name, "args": args, "note": note, "suggested": True})
            if suggested_lines:
                exec_results.extend(suggested_lines)
        # Record combined metadata (suggested plan steps + any parallel sub-agent meta)
        self._last_execution_steps = list(plan_meta) + (parallel_meta if 'parallel_meta' in locals() else [])
        current_time = self._extract_current_time()
        if current_time:
            prompt = f"Current time: {current_time}\n\n{prompt}"
        if exec_results:
            exec_text = "\n".join(exec_results)
            prompt = f"{prompt}\n\nTool execution results:\n{exec_text}"
        result = await self.agent.run(prompt, message_history=message_history)
        try:
            self._last_messages = result.all_messages()
        except Exception:
            self._last_messages = None
        self._last_assistant_reply = self._extract_user_reply(result.output)
        return result.output

    async def run_stream(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
        skip_plan_execution: bool = True,  # 默認跳過 plan execution，讓 agent 自己調用工具
    ):
        """Streamed version of run(): yields chunks from philosopher/subagents/main agent as they produce output."""
        # 每次執行前從資料庫重載配置
        self._reload_model_from_db()
        
        self._previous_user_prompt = self._last_user_prompt
        self._last_user_prompt = prompt
        prompt, explicit_subagents = self._prepare_prompt(prompt)
        prompt, trigger_state = self._apply_keyword_triggers(prompt)

        # 如果啟用 skip_plan_execution，直接讓 agent.run_stream() 自己調用工具
        if skip_plan_execution:
            # 只處理 sub-agents（如果需要）
            auto_subagents = (
                []
                if explicit_subagents
                else await self._decide_sub_agents(prompt, message_history=message_history)
            )
            parallel_subagents = explicit_subagents or auto_subagents
            
            if parallel_subagents:
                order, tasks = self._start_subagent_tasks(parallel_subagents, prompt)
                if order and tasks:
                    parallel_results, parallel_meta = await self._collect_subagent_results(
                        order, tasks, prompt
                    )
                    self._last_execution_steps = parallel_meta
                    if parallel_results:
                        exec_text = "\n".join(parallel_results)
                        prompt = f"{prompt}\n\nSub-agent results:\n{exec_text}"
            
            # 直接調用 agent.run_stream()，捕獲 MCP 工具錯誤
            try:
                async with self.agent.run_stream(
                    user_prompt=prompt, message_history=message_history
                ) as result:
                    collected = ""
                    try:
                        async for chunk in result.stream_text(delta=True):
                            if not chunk:
                                continue
                            collected += chunk
                            yield chunk
                    except Exception as stream_error:
                        # 捕獲 stream 過程中的錯誤（例如 MCP 工具錯誤）
                        error_msg = str(stream_error)
                        logger.warning(f"Tool execution error during streaming: {error_msg}")
                        
                        # yield 錯誤提示給 LLM，讓它生成友好回應
                        error_prompt = (
                            f"\n\n[System Note: A tool execution error occurred: {error_msg}. "
                            "Please provide a helpful response explaining the service is temporarily unavailable.]"
                        )
                        yield error_prompt
                        
                    try:
                        self._last_messages = result.all_messages()
                    except Exception:
                        self._last_messages = None
                    self._last_assistant_reply = self._extract_user_reply(collected)
                return
            except Exception as e:
                # 捕獲 context manager 層級的錯誤
                error_msg = str(e)
                logger.warning(f"Tool execution error in agent.run_stream(): {error_msg}")
                
                # 將錯誤作為執行結果附加到 prompt
                error_context = (
                    f"\n\nTool execution error:\n{error_msg}\n\n"
                    "Please provide a helpful response to the user explaining that the external service "
                    "is temporarily unavailable and suggest alternatives if possible."
                )
                
                # 重新調用 agent.run_stream()，這次不呼叫工具，只是讓 LLM 看到錯誤並生成回應
                try:
                    async with self.agent.run_stream(
                        user_prompt=prompt + error_context, message_history=message_history
                    ) as result:
                        collected = ""
                        async for chunk in result.stream_text(delta=True):
                            if not chunk:
                                continue
                            collected += chunk
                            yield chunk
                        try:
                            self._last_messages = result.all_messages()
                        except Exception:
                            self._last_messages = None
                        self._last_assistant_reply = self._extract_user_reply(collected)
                    return
                except Exception as final_error:
                    # 最後的 fallback - 建立簡單的錯誤說明讓 agent 理解
                    logger.error(f"All retry attempts failed: {final_error}")
                    final_prompt = (
                        f"The user asked: {self._last_user_prompt}\n\n"
                        f"A tool execution error occurred: {error_msg}\n"
                        "The external service is currently unavailable. "
                        "Please provide a helpful and friendly response to the user."
                    )
                    # 最後一次嘗試
                    try:
                        async with self.agent.run_stream(user_prompt=final_prompt) as result:
                            async for chunk in result.stream_text(delta=True):
                                if chunk:
                                    yield chunk
                        return
                    except Exception:
                        # 真的完全失敗了
                        yield "抱歉，系統暫時無法處理您的請求。請稍後再試。"
                        return

        # 舊的 plan execution 模式（保留以備需要）
        # Skills are now tool-based (use_skill tool) - no automatic injection
        plan_list = await self._build_plan_list(prompt, message_history=message_history)
        if explicit_subagents:
            plan_list = self._filter_plan_subagent_steps(plan_list, explicit_subagents)
        has_subagent_in_plan = self._plan_requests_subagent(plan_list)
        auto_subagents = (
            []
            if explicit_subagents or has_subagent_in_plan
            else await self._decide_sub_agents(prompt, message_history=message_history)
        )
        parallel_subagents = explicit_subagents or auto_subagents
        background_mode = self._resolve_background_mode(trigger_state)
        exec_results: list[str] = []
        step_outputs: list[str] = []
        steps_meta: list[dict[str, Any]] = []
        current_time = None
        parallel_results: list[str] = []
        parallel_meta: list[dict[str, Any]] = []
        order, tasks = self._start_subagent_tasks(parallel_subagents, prompt)
        pending_parallel = bool(order and tasks)
        if pending_parallel and (not background_mode or not plan_list):
            parallel_results, parallel_meta = await self._collect_subagent_results(
                order, tasks, prompt
            )
            steps_meta.extend(parallel_meta)
            exec_results.extend(parallel_results)
            pending_parallel = False
        if parallel_results or plan_list or pending_parallel:
            # Present the plan as suggestions (do not execute tools in plan mode).
            yield "<plan-suggestion>\n"
            suggestion_lines: list[str] = []
            steps_meta: list[dict[str, Any]] = []
            # include parallel results first (no change)
            for line in parallel_results:
                yield line + "\n"
                suggestion_lines.append(line)
            # present suggested plan steps
            for idx, step in enumerate(plan_list, start=1):
                tool_name = step.get("tool") if isinstance(step, dict) else None
                args = step.get("args", {}) if isinstance(step, dict) else {}
                note = step.get("note") if isinstance(step, dict) else None
                header = f"Suggested Step {idx}: {tool_name}"
                if note:
                    header += f"  ({note})"
                args_text = ""
                if args:
                    try:
                        args_text = f" args: {json.dumps(args, ensure_ascii=False)}"
                    except Exception:
                        args_text = f" args: {str(args)}"
                line = header + args_text
                yield line + "\n"
                suggestion_lines.append(line)
                steps_meta.append({"tool": tool_name, "args": args, "note": note, "suggested": True})

            # if parallel tasks are still pending, collect their results
            if pending_parallel:
                parallel_results, parallel_meta = await self._collect_subagent_results(
                    order, tasks, prompt
                )
                steps_meta.extend(parallel_meta)
                suggestion_lines.extend(parallel_results)
                for line in parallel_results:
                    yield line + "\n"

            # finalize suggestion block
            yield "</plan-suggestion>\n"
            self._last_execution_steps = steps_meta
            current_time = self._extract_current_time()
            exec_text = "\n".join(exec_results + suggestion_lines)
            prompt = f"{prompt}\n\nTool suggestion results:\n{exec_text}"
        if current_time:
            prompt = f"Current time: {current_time}\n\n{prompt}"
        
        # 捕獲最終 agent.run_stream() 的錯誤（包括 MCP 工具錯誤）
        try:
            async with self.agent.run_stream(
                user_prompt=prompt, message_history=message_history
            ) as result:
                collected = ""
                try:
                    async for chunk in result.stream_text(delta=True):
                        if not chunk:
                            continue
                        collected += chunk
                        yield chunk
                except Exception as stream_error:
                    # 捕獲 stream 過程中的錯誤（例如 MCP 工具錯誤）
                    error_msg = str(stream_error)
                    logger.warning(f"Tool execution error during streaming: {error_msg}")
                    
                    # 建立錯誤上下文給 agent
                    error_context = (
                        f"\n\n[System Note: A tool execution error occurred: {error_msg}. "
                        "Please provide a helpful response to the user explaining the situation "
                        "and suggesting alternatives if applicable.]"
                    )
                    yield error_context
                    
                try:
                    self._last_messages = result.all_messages()
                except Exception:
                    self._last_messages = None
                self._last_assistant_reply = self._extract_user_reply(collected)
        except Exception as e:
            # 捕獲 context manager 層級的錯誤
            error_msg = str(e)
            logger.warning(f"Error in agent.run_stream(): {error_msg}")
            
            # 讓 agent 看到錯誤並生成回應
            error_prompt = (
                f"The user asked: {self._last_user_prompt}\n\n"
                f"A tool execution error occurred: {error_msg}\n"
                "Please provide a helpful and friendly response explaining the situation."
            )
            try:
                async with self.agent.run_stream(user_prompt=error_prompt) as result:
                    async for chunk in result.stream_text(delta=True):
                        if chunk:
                            yield chunk
            except Exception:
                # 真的完全失敗了
                yield "抱歉，系統暫時無法處理您的請求。請稍後再試。"
