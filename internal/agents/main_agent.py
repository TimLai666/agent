from httpx import AsyncClient
import json
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
from internal.set_tools import add_all_tools
from internal.sub_agents import SubAgentRegistry, load_sub_agent_registry
import sys
import inspect
import asyncio
import functools
from typing import Any, cast
from pydantic_ai.mcp import MCPServerStdio

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
    ) -> "MainAgent":
        if sub_agents is None:
            try:
                sub_agents = load_sub_agent_registry(base_config, env, http_client)
            except Exception:
                logger.exception("Failed to load sub-agents; continuing without them")
                sub_agents = SubAgentRegistry({}, {})

        config = load_agent_config_chain([cls.ENV_PREFIX], base_config, env)
        model = create_openai_model(config, http_client)
        instructions = get_prompt(cls.PROMPT_KEY)
        if sub_agents and not sub_agents.is_empty():
            instructions += (
                "\n\nSub-agents are available via tools: list_sub_agents, ask_sub_agent."
            )
        # build MCP servers for browser tools
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

        mcp_servers = [browser_use_headed, browser_use_headless]

        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=instructions,
            tools=[],
            model_settings={"temperature": config.temperature},
            mcp_servers=mcp_servers,
        )
        planner_agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions="你是嚴格的工具規劃器，只能輸出 JSON。",
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        # register global tools directly on the main agent
        # Wrap agent.tool_plain temporarily so that each registered tool is
        # wrapped to log calls, arguments, results and exceptions.
        original_tool_plain = getattr(agent, "tool_plain", None)
        if original_tool_plain:
            def logging_tool_plain(func):
                # create a wrapped callable that logs on invocation
                if inspect.iscoroutinefunction(func):
                    @functools.wraps(func)
                    async def wrapped_async(*args, **kwargs):
                        logger.info("Tool call start: %s args=%s kwargs=%s", func.__name__, args, kwargs)
                        try:
                            res = await func(*args, **kwargs)
                            logger.info("Tool call end: %s result=%s", func.__name__, res)
                            return res
                        except Exception:
                            logger.exception("Tool %s raised an exception", func.__name__)
                            raise
                    wrapped_callable = wrapped_async
                else:
                    @functools.wraps(func)
                    def wrapped_sync(*args, **kwargs):
                        logger.info("Tool call start: %s args=%s kwargs=%s", func.__name__, args, kwargs)
                        try:
                            res = func(*args, **kwargs)
                            logger.info("Tool call end: %s result=%s", func.__name__, res)
                            return res
                        except Exception:
                            logger.exception("Tool %s raised an exception", func.__name__)
                            raise
                    wrapped_callable = wrapped_sync

                # delegate to the original registration API with the wrapped callable
                return original_tool_plain(wrapped_callable)

            cast(Any, agent).tool_plain = logging_tool_plain

        main_agent = cls(agent, philosopher, sub_agents, planner_agent)
        try:
            add_all_tools(
                agent,
                config.model_name,
                config.base_url,
                config.api_key,
                extra_tools=[
                    main_agent.ask_philosopher,
                    main_agent.list_sub_agents,
                    main_agent.ask_sub_agent,
                ],
            )
            logger.info("Registered tools on MainAgent")
        except Exception:
            logger.exception("Failed to add tools to main agent; continuing without external tools")
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
    ) -> None:
        self.agent = agent
        self.philosopher = philosopher
        self.sub_agents = sub_agents
        self._planner_agent = planner_agent or agent
        self._last_messages: list[ModelRequest | ModelResponse] | None = None
        self._last_execution_steps: list[dict[str, Any]] = []
        # tools are registered via add_all_tools during create()

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
            if isinstance(parsed, dict) and ("execution_plan" in parsed or "plan" in parsed):
                return parsed
            # if the parsed dict itself *is* a plan
            if isinstance(parsed, dict) and ("steps" in parsed or "plan" in parsed or "execution_plan" in parsed):
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
            if text[i] != '{':
                i += 1
                continue
            depth = 0
            j = i
            while j < text_len:
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        snippet = text[i : j + 1]
                        try:
                            parsed = json.loads(snippet)
                            if isinstance(parsed, dict) and (
                                "execution_plan" in parsed or "plan" in parsed or "steps" in parsed
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

    async def execute_plan(self, plan_obj: dict) -> list[str]:
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
            header = f"Step {idx+1}: {tool_name}"
            if note:
                header += f"  ({note})"
            results.append(header)
            step_meta: dict[str, Any] = {"tool": tool_name, "args": args, "note": note}

            registered = getattr(self.agent, "_function_tools", {}) or {}
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
                            question = self._build_sub_agent_prompt(note, current_args)
                        current_args = {"question": question}
                    elif current_tool in {"philosopher", "哲學家"}:
                        question = self._build_sub_agent_prompt(note, current_args)
                        current_tool = "ask_philosopher"
                        current_args = {"question": question}
                    elif current_tool == "ask_sub_agent":
                        name = ""
                        if isinstance(current_args, dict):
                            name = str(current_args.get("name", "")).strip().lower()
                        if name in {"philosopher", "哲學家", "philosopher-co-agent"}:
                            question = ""
                            if isinstance(current_args, dict):
                                question = str(current_args.get("prompt", "")).strip()
                            if not question:
                                question = self._build_sub_agent_prompt(note, current_args)
                            current_tool = "ask_philosopher"
                            current_args = {"question": question}

                if (
                    self.sub_agents
                    and isinstance(current_tool, str)
                    and self.sub_agents.get_agent(current_tool)
                    and "ask_sub_agent" in allowed_names
                ):
                    prompt = self._build_sub_agent_prompt(note, current_args)
                    current_args = {"name": current_tool, "prompt": prompt}
                    current_tool = "ask_sub_agent"

                if not current_tool:
                    current_error = "Missing 'tool' field."
                elif current_tool not in allowed_names:
                    current_error = f"Tool '{current_tool}' is not registered."
                else:
                    if current_args:
                        current_args = self._resolve_args(current_args, step_outputs)
                    tool_def = registered.get(str(current_tool)) if isinstance(current_tool, str) else None
                    if tool_def is None:
                        current_error = f"Tool '{current_tool}' declared but not found on agent runtime."
                    elif getattr(tool_def, "takes_ctx", False):
                        current_error = f"Tool '{current_tool}' requires context and cannot be called directly."
                    else:
                        callable_obj = tool_def.function
                        try:
                            try:
                                schema = tool_def.function_schema.json_schema or {}
                                expected_keys = list((schema.get("properties") or {}).keys())
                            except Exception:
                                expected_keys = []
                            if current_args and expected_keys:
                                expected_set = set(expected_keys)
                                if not set(current_args.keys()).issubset(expected_set):
                                    if len(expected_keys) == 1 and len(current_args) == 1:
                                        current_args = {expected_keys[0]: next(iter(current_args.values()))}
                            if current_tool == "get_stock_history":
                                ticker = current_args.get("ticker_symbol")
                                if isinstance(ticker, str):
                                    if ticker.isdigit() and not ticker.upper().endswith(".TW"):
                                        current_args["ticker_symbol"] = f"{ticker}.TW"
                                period = current_args.get("period")
                                if isinstance(period, str):
                                    normalized = period.lower()
                                    if normalized in {"month", "1m"}:
                                        current_args["period"] = "1mo"
                                    elif normalized in {"3m"}:
                                        current_args["period"] = "3mo"
                            elif current_tool == "get_current_stock_price":
                                ticker = current_args.get("ticker_symbol")
                                if isinstance(ticker, str):
                                    if ticker.isdigit() and not ticker.upper().endswith(".TW"):
                                        current_args["ticker_symbol"] = f"{ticker}.TW"
                                        current_args.setdefault("is_taiwan_stock", "True")
                            logger.info("Executing tool '%s' with args: %s", current_tool, current_args)
                            if inspect.iscoroutinefunction(callable_obj):
                                res = await callable_obj(**current_args)
                            else:
                                maybe = callable_obj(**current_args) if current_args else callable_obj()
                                if asyncio.iscoroutine(maybe):
                                    res = await maybe
                                else:
                                    res = maybe
                            logger.info("Tool '%s' execution result: %s", current_tool, res)
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
                    results.append("  -> recovery failed: no corrected tool call returned")
                    step_meta["error"] = "recovery failed: no corrected tool call returned"
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
        tools_text = self._format_tools_context().strip()

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
            "只輸出 JSON，格式：{\"tool\": \"tool_name\", \"args\": {\"key\": \"value\"}}。\n"
            "如需使用前一步結果，可用 \"$last\" 或 \"$step1\" 佔位符。\n"
        )

        for attempt in range(2):
            try:
                retry_hint = ""
                if attempt == 1:
                    retry_hint = "上一次沒有輸出合法 JSON。這次只輸出 JSON，不能有其他文字。\n\n"
                result = await self._planner_agent.run(retry_hint + prompt)
                out = (result.output or "").strip()
                parsed = json.loads(out)
                if isinstance(parsed, dict) and parsed.get("tool"):
                    return {"tool": parsed.get("tool"), "args": parsed.get("args", {})}
            except Exception:
                logger.exception("Tool recovery failed")
        return None

    async def _should_consult_philosopher(
        self, prompt: str, message_history: list[ModelRequest | ModelResponse] | None = None
    ) -> bool:
        """以主 agent 模型決定是否需要與哲學家討論。

        會向 `self.agent` 發出簡短判定請求（回傳 YES/NO 與簡短原因）。
        若模型失敗或回應不明確，採保守策略：回傳 True 以確保討論。
        """
        # 使用嚴格 JSON 回應格式：{"consult": true|false, "reason": "..."}
        # 範例幫助模型學習何種問題需要討論（簡單事實性問題不需要）
        decider = (
            "你是主 agent 的決策助手。請判斷下列使用者輸入是否需要向哲學家 co-agent 進行多輪內省討論。"
            " 嚴格回傳一個有效 JSON 對象，不要包含其他文字。JSON 格式：{'consult': true/false, 'reason': '短理由'}。"
            " **重要**：在這個判定步驟中，請不要呼叫任何工具或嘗試執行外部函式；僅依靠你的語言理解回傳 JSON。"
            " 範例：\n"
            "輸入: '現在幾點'\n輸出: {" + '"consult": false, "reason": "簡單事實性查詢"}' + "\n"
            "輸入: '評估不同投資組合的風險與報酬'\n輸出: {" + '"consult": true, "reason": "需要權衡與推理"}' + "\n\n"
            "使用者輸入：\n" + prompt + "\n\n請只回傳 JSON，且不要呼叫任何工具："
        )

        try:
            result = await self.agent.run(decider, message_history=message_history)
            out = (result.output or "").strip()
            # 嘗試解析 JSON
            try:
                parsed = json.loads(out)
                consult = bool(parsed.get("consult", False))
                return consult
            except Exception:
                # 若模型回傳包含 JSON 片段，嘗試從其中抽取 true/false
                lower = out.lower()
                if "true" in lower or "yes" in lower or "是" in lower or "需要" in lower:
                    return True
                if "false" in lower or "no" in lower or "否" in lower or "不需要" in lower:
                    return False
                # 解析失敗：為避免多餘討論，採保守策略：不討論
                logger.info("Decision response not parseable; defaulting to NO consult. Response: %s", out)
                return False
        except Exception:
            logger.exception("Decision call to main agent failed; defaulting to NO consult")
            return False

    async def ask_philosopher(self, question: str) -> str:
        """Tool: forward question to philosopher co-agent."""
        logger.info("Main agent -> philosopher")
        print("[LOG] main -> philosopher")
        # prefer streaming if available
        if hasattr(self.philosopher, "run_stream"):
            collected = ""
            async for chunk in self.philosopher.run_stream(question):
                collected += chunk
            return collected
        return await self.philosopher.run(question)

    def list_sub_agents(self) -> list[dict[str, str]]:
        """Tool: list available sub-agents (name + short description)."""
        if not self.sub_agents:
            return []
        return self.sub_agents.list_summaries()

    async def ask_sub_agent(self, name: str, prompt: str) -> str:
        """Tool: delegate a task to a sub-agent by name."""
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
        tools_meta = getattr(self.agent, "_function_tools", None)
        if tools_meta:
            tools_lines = ["Available tools:"]
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
                    tools_lines.append(f"- {name}{sig}: {doc}")
                else:
                    tools_lines.append(f"- {name}{sig}")
            return "\n".join(tools_lines) + "\n\n"
        return "Available tools: (none)\n\n"

    def _build_sub_agent_prompt(self, note: str | None, args: dict[str, Any] | None) -> str:
        if args:
            for key in ("prompt", "question", "task", "input"):
                value = args.get(key)
                if value:
                    return str(value)
        if note:
            return note
        return "請協助處理此步驟。"

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
    ) -> dict | None:
        tools_text = self._format_tools_context()
        sub_agents_text = self._format_sub_agents_context()
        retry_hint = ""
        if attempt > 1:
            retry_hint = (
                "你上一次沒有輸出合法 JSON。這次只能輸出 JSON。\n"
                "除非完全沒有工具可用，否則不得輸出空 plan；必須至少一個步驟。\n\n"
            )

        plan_prompt = (
            "你必須先規劃工具呼叫再回答。只輸出 JSON，格式固定為 {\"plan\": [ ... ]}。\n"
            "每個步驟必須包含 tool 欄位；需要參數時加入 args 物件，沒有參數就省略或用 {}。\n"
            "若不需要工具，回傳 {\"plan\": []}。不要寫分析或其他文字。\n"
            "若要委派給 sub-agent，使用工具 ask_sub_agent，args 為 {\"name\": \"...\", \"prompt\": \"...\"}。\n"
            "哲學家不是 sub-agent，若需請教哲學家，使用工具 ask_philosopher，參數 question。\n"
            "如果後續步驟需要前一步的輸出，使用 \"$last\" 或 \"$step1\" 這類佔位符。\n\n"
            "常見需求對應工具（若符合就直接用）：\n"
            "- 詢問現在時間：get_now\n"
            "- 查某日期是星期幾：get_weekday，參數 date_str\n"
            "- 擲骰子：roll_dice\n"
            "- 從清單隨機挑一個：random_pick，參數 items\n"
            "- 目前工作目錄：get_current_directory\n"
            "- 列出目錄檔案：list_files_in_directory，參數 dir\n"
            "- 讀取檔案內容：read_file，參數 file_path\n"
            "- 作業系統/架構：get_platform_info\n"
            "- 股價/股史：get_current_stock_price 或 get_stock_history\n\n"
            + retry_hint
            + tools_text
            + sub_agents_text
            + f"使用者需求：\n{prompt}\n\n"
            "只輸出 JSON。"
        )

        try:
            result = await self._planner_agent.run(plan_prompt)
            out = (result.output or "").strip()
            logger.info("Planner output (attempt %s): %s", attempt, out)
            return await self._extract_execution_plan(out)
        except Exception:
            logger.exception("Failed to request execution plan")
            return None

    async def _ensure_eager_execution(
        self,
        prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> list[str]:
        plan_obj = await self._request_execution_plan(prompt, message_history=message_history, attempt=1)
        if plan_obj is None or _plan_is_empty(plan_obj):
            plan_obj = await self._request_execution_plan(prompt, message_history=message_history, attempt=2)
            if plan_obj is None or _plan_is_empty(plan_obj):
                return []
        if not plan_obj:
            return []
        return await self.execute_plan(plan_obj)

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
        summary = """請判斷下列討論與主 agent 的候選回答是否已足以得出最終答案。只回傳 JSON：{" + '"end": true/false, "reason": "短理由"}' + "，不要其他文字。\n\n討論摘要：\n"""
        for speaker, text in discussion:
            summary += f"{speaker}: {text}\n"
        if last_main_answer:
            summary += f"\n主 agent 候選回答：\n{last_main_answer}\n"

        summary += "\n**重要**：不要呼叫任何工具。只依據討論判斷並回傳 JSON。"

        try:
            res = await self.agent.run(summary, message_history=message_history)
            out = (res.output or "").strip()
            try:
                parsed = json.loads(out)
                return bool(parsed.get("end", False))
            except Exception:
                # 尝试基于可解析的文字作简单判定；若无法解析则不结束
                lower = out.lower()
                if "true" in lower or "yes" in lower or "可以" in lower or "結束" in lower:
                    return True
                if "false" in lower or "no" in lower or "不" in lower or "還需要" in lower:
                    return False
                # 解析失敗：不回退、不使用任何後備規則，直接回傳 False（繼續討論）
                return False
        except Exception:
            logger.exception("End-discussion decision call failed; defaulting to NO end")
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
            " 並回傳嚴格的 JSON：{\"depth\": \"very_shallow|shallow|medium|deep|very_deep\", \"rounds\": 1..5}."
            " 範例：\n輸入：'現在幾點'\n輸出：{\"depth\": \"very_shallow\", \"rounds\": 1}\n"
            "輸入：'評估不同投資組合的風險與報酬'\n輸出：{\"depth\": \"very_deep\", \"rounds\": 5}\n\n使用者輸入：\n"
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
                if depth not in ("very_shallow", "shallow", "medium", "deep", "very_deep"):
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
    ) -> str:
        exec_results = await self._ensure_eager_execution(prompt, message_history=message_history)
        if exec_results:
            exec_text = "\n".join(exec_results)
            prompt = f"{prompt}\n\nTool execution results:\n{exec_text}"
        result = await self.agent.run(prompt, message_history=message_history)
        try:
            self._last_messages = result.all_messages()
        except Exception:
            self._last_messages = None
        return result.output

    async def run_stream(self, prompt: str, message_history: list[ModelRequest | ModelResponse] | None = None):
        """Streamed version of run(): yields chunks from philosopher/subagents/main agent as they produce output."""
        exec_results = await self._ensure_eager_execution(prompt, message_history=message_history)
        if exec_results:
            exec_text = "\n".join(exec_results)
            yield "<tool-execution>\n"
            for line in exec_results:
                yield line + "\n"
            yield "</tool-execution>\n"
            discussion_lines = []
            for step in self._last_execution_steps:
                if step.get("tool") == "ask_philosopher":
                    if "result" in step:
                        discussion_lines.append(str(step["result"]))
                    elif "error" in step:
                        discussion_lines.append(f"Error: {step['error']}")
            if discussion_lines:
                yield "<discussion>\n"
                for line in discussion_lines:
                    yield line + "\n"
                yield "</discussion>\n"
            prompt = f"{prompt}\n\nTool execution results:\n{exec_text}"
        async with self.agent.run_stream(user_prompt=prompt, message_history=message_history) as result:
            async for chunk in result.stream_text(delta=True):
                if not chunk:
                    continue
                yield chunk
            try:
                self._last_messages = result.all_messages()
            except Exception:
                self._last_messages = None
