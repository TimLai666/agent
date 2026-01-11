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

        try:
            add_all_tools(agent, config.model_name, config.base_url, config.api_key)
            logger.info("Registered tools on MainAgent")
        except Exception:
            logger.exception("Failed to add tools to main agent; continuing without external tools")
        finally:
            # restore original registration function if we replaced it
            if original_tool_plain:
                cast(Any, agent).tool_plain = original_tool_plain
        return cls(agent, philosopher, sub_agents)

    def __init__(
        self,
        agent: Agent[None, str],
        philosopher: PhilosopherCoAgent,
        sub_agents: SubAgentRegistry | None = None,
    ) -> None:
        self.agent = agent
        self.philosopher = philosopher
        self.sub_agents = sub_agents
        self._last_messages: list[ModelRequest | ModelResponse] | None = None
        # register tool functions so agent can call them; defining as methods
        try:
            # calling tool_plain with the bound method registers it
            cast(Any, self.agent).tool_plain(self.ask_philosopher)
            # tools from internal.set_tools were added during create()
        except Exception:
            # registration failures shouldn't break initialization
            logger.debug("Tool registration skipped or failed during init")
        if self.sub_agents and not self.sub_agents.is_empty():
            try:
                cast(Any, self.agent).tool_plain(self.list_sub_agents)
                cast(Any, self.agent).tool_plain(self.ask_sub_agent)
            except Exception:
                logger.debug("Sub-agent tool registration skipped or failed during init")

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

        for idx, step in enumerate(plan):
            tool_name = step.get("tool") if isinstance(step, dict) else None
            args = step.get("args", {}) if isinstance(step, dict) else {}
            note = step.get("note") if isinstance(step, dict) else None
            header = f"Step {idx+1}: {tool_name}"
            if note:
                header += f"  ({note})"
            results.append(header)

            registered = getattr(self.agent, "_registered_tools", []) or []
            allowed_names = {t.get("name") for t in registered if isinstance(t, dict)}

            attempts = 0
            current_tool = tool_name
            current_args = args
            current_error = ""
            while True:
                if not current_tool:
                    current_error = "Missing 'tool' field."
                elif current_tool not in allowed_names:
                    current_error = f"Tool '{current_tool}' is not registered."
                else:
                    callable_obj = getattr(self.agent, current_tool, None)
                    if callable_obj is None:
                        current_error = f"Tool '{current_tool}' declared but not found on agent runtime."
                    else:
                        try:
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
                            break
                        except Exception as e:
                            logger.exception("Error executing tool %s", current_tool)
                            current_error = f"Execution error: {e}"

                if attempts >= self.TOOL_RECOVERY_MAX_ATTEMPTS:
                    if current_error:
                        results.append(f"  -> execution error: {current_error}")
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
                    break
                current_tool = recovery.get("tool")
                current_args = recovery.get("args", {})

        return results

    async def _recover_tool_call(
        self,
        tool: str | None,
        args: dict[str, Any] | None,
        error: str,
        note: str | None,
    ) -> dict[str, Any] | None:
        tools_meta = getattr(self.agent, "_registered_tools", []) or []
        if tools_meta:
            tools_lines = ["Available tools:"]
            for t in tools_meta:
                sig = t.get("signature", "()")
                doc = t.get("doc", "").splitlines()[0] if t.get("doc") else ""
                tools_lines.append(f"- {t.get('name')}{sig}: {doc}")
            tools_text = "\n".join(tools_lines)
        else:
            tools_text = "Available tools: (none)"

        sub_agents_text = self._format_sub_agents_context().strip()
        note_text = f"Note: {note}\n" if note else ""
        prompt = (
            "A tool call failed. Reflect briefly on why, fix the tool name and/or args, then return only JSON.\n"
            "You may call ask_sub_agent if it helps.\n\n"
            f"{tools_text}\n"
            f"{sub_agents_text}\n"
            f"{note_text}"
            f"Failed tool: {tool}\n"
            f"Args: {args}\n"
            f"Error: {error}\n\n"
            "Return JSON only in this format: {\"tool\": \"tool_name\", \"args\": {\"key\": \"value\"}}\n"
        )

        try:
            result = await self.agent.run(prompt)
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
        # 根據 prompt 判斷是否要與哲學家多輪討論（由主 agent 模型決定）
        if not await self._should_consult_philosopher(prompt, message_history=message_history):
            # 直接由主 agent 回答（較快速路徑）
            result = await self.agent.run(prompt, message_history=message_history)
            try:
                self._last_messages = result.all_messages()
            except Exception:
                self._last_messages = None
            output = result.output

            return output

        # 多輪討論流程：主 agent 與哲學家 co-agent 一來一回討論，直到哲學家表示可作為結論或達到最大輪數
        # 決定討論內容深度（shallow/medium/deep）由主 agent 模型決定
        try:
            depth_choice = await self._decide_discussion_depth(prompt, message_history=message_history)
            depth_label = depth_choice.get("depth", "medium")
            max_rounds = int(depth_choice.get("rounds", 2))
        except Exception:
            depth_label = "medium"
            max_rounds = 2
        discussion: list[tuple[str, str]] = []
        current_prompt = prompt

        for r in range(max_rounds):
            round_tag = f"回合 {r+1}"
            # 向哲學家請求分析/內省
            try:
                # depth instruction text (English)
                if depth_label == "very_shallow":
                    depth_instr = "Provide a very concise summary: give the direct conclusion or key answer in one or two lines."
                elif depth_label == "shallow":
                    depth_instr = "Provide a brief, focused analysis listing the key points and the most critical uncertainties."
                elif depth_label == "deep":
                    depth_instr = "Provide a deep, step-by-step introspective analysis, detailing uncertainties, assumptions, evidence, counterarguments, and verification steps."
                elif depth_label == "very_deep":
                    depth_instr = "Provide a very deep, comprehensive introspective analysis, including detailed evidence evaluation, alternative perspectives, and risk assessment."
                else:
                    depth_instr = "Provide a moderate-depth analysis listing main uncertainties, assumptions, and suggested checks."

                # include available tools for philosopher to reference
                tools_meta = getattr(self.agent, "_registered_tools", None)
                if tools_meta:
                    tools_lines = ["Available tools:"]
                    for t in tools_meta:
                        sig = t.get("signature", "()")
                        doc = t.get("doc", "").splitlines()[0] if t.get("doc") else ""
                        tools_lines.append(f"- {t.get('name')}{sig}: {doc}")
                    tools_text = "\n".join(tools_lines) + "\n\n"
                else:
                    tools_text = "Available tools: (none)\n\n"
                sub_agents_text = self._format_sub_agents_context()

                phil_prompt = (
                    f"{round_tag} - {depth_instr} Before analyzing, explicitly define the discussion scope: list what to focus on (Focus) and what is out of scope for this discussion (Out of scope).\n\n"
                    + tools_text
                    + sub_agents_text
                    + "SUB-AGENTS: If any sub-agent is relevant, explicitly recommend which one(s) to consult by name.\n\n"
                    + f"Then analyze the following question and list uncertainties, assumptions, and reasoning steps:\n\n{current_prompt}\n\n"
                    "CONCISENESS RULES: Keep responses short and focused. First give a one-line Focus summary, then list up to 3 key uncertainties (bulleted), then a very short analysis (no more than 4 sentences)."
                    "FACTS & TOOLS: If you require factual data or live information, produce a minimal 'execution_plan' JSON only (no long analysis) with the key 'plan' listing the necessary tool calls."
                    "The Main Agent will execute that plan and return results for you to continue analysis. IMPORTANT: Only reference tools from the 'Available tools' list above and use exact tool names."
                    " Each step object must have 'tool' (string matching an available tool name exactly), optional 'args' (object), and optional 'note' (string)."
                    " Place the JSON on its own line so it can be parsed separately."
                )
                logger.info("Main agent requesting philosopher analysis (round %d)", r + 1)
                print(f"[LOG] main -> philosopher (deliberation) round {r+1}")
                phil_resp = await self.philosopher.run(phil_prompt)
            except Exception:
                logger.exception("Philosopher co-agent failed during deliberation; breaking")
                break

            discussion.append(("Philosopher", phil_resp))
            # If philosopher provided an execution plan JSON, parse and execute it
            try:
                plan_obj = await self._extract_execution_plan(phil_resp)
                # If no plan found but philosopher text suggests needing facts, ask for a plan
                if plan_obj is None:
                    need_keywords = [
                        "需要查", "需要查證", "需要查詢", "需要確認", "核實", "verify", "check", "need to",
                    ]
                    lower = (phil_resp or "").lower()
                    if any(k in lower for k in need_keywords):
                        logger.info("Philosopher analysis indicates need for factual checks; requesting execution_plan")
                        try:
                            plan_request = (
                                "Your previous analysis suggests you need factual checks or live data. "
                                "Please output a minimal execution_plan JSON (one line) with key 'plan' listing the tool calls required. "
                                "Use only the Available tools names exactly."
                            )
                            plan_only = await self.philosopher.run(plan_request)
                            plan_obj = await self._extract_execution_plan(plan_only) or None
                            if plan_obj:
                                # append philosopher's plan-only response to discussion
                                discussion.append(("PhilosopherPlanRequest", plan_only))
                        except Exception:
                            logger.exception("Failed to request execution_plan from philosopher")

                if plan_obj:
                    logger.info("Philosopher provided an execution plan; executing")
                    exec_results = await self.execute_plan(plan_obj)
                    exec_text = "\n".join(exec_results)
                    discussion.append(("Execution", exec_text))
                    # Inform philosopher of the execution results and ask for follow-up analysis
                    try:
                        follow_prompt = (
                            "The main agent executed the plan and produced the following results:\n"
                            + exec_text
                            + "\n\nPlease update your analysis based on these results. If this changes focus or next steps, state them."
                        )
                        phil_follow = await self.philosopher.run(follow_prompt)
                        discussion.append(("Philosopher", phil_follow))
                    except Exception:
                        logger.exception("Failed to get follow-up analysis from philosopher after execution")
            except Exception:
                logger.exception("Failed to parse or execute philosopher plan")

            # 主 agent 基於目前討論產生候選回答
            main_input = f"原始問題：\n{prompt}\n\n討論紀錄：\n"
            for speaker, text in discussion:
                main_input += f"{speaker}: {text}\n\n"
            main_input += "請基於上述討論，提出一個候選回答（標註是否為最終結論）："

            main_result = await self.agent.run(main_input, message_history=message_history)
            main_answer = main_result.output
            discussion.append(("MainAgent", main_answer))

            # 將主 agent 的候選回答回饋給哲學家，請其評論並指出是否可作為結論
            try:
                critique_prompt = (
                    "Review the Main Agent's candidate answer below. Point out errors, omissions, and suggestions for improvement,"
                    " and indicate whether this can be considered the final conclusion. If yes, provide a clear 'Conclusion: ...'; otherwise, provide corrections and next steps:\n\n"
                    + main_answer
                    + "\n\nOriginal question:\n"
                    + prompt
                )
                print(f"[LOG] main -> philosopher (critique) round {r+1}")
                phil_crit = await self.philosopher.run(critique_prompt)
            except Exception:
                logger.exception("Philosopher co-agent failed during critique; breaking")
                break

            discussion.append(("Philosopher", phil_crit))

            # 讓主 agent 判斷是否要結束討論（以模型回應為主，無法解析時退回哲學家關鍵字）
            try:
                should_end = await self._should_end_discussion(
                    discussion, last_main_answer=main_answer, message_history=message_history
                )
            except Exception:
                should_end = False

            if should_end:
                break

            # 否則以哲學家回饋更新 current_prompt，進入下一輪
            current_prompt = f"{prompt}\n\n哲學家回饋：\n{phil_crit}\n\n請根據回饋修正並提出新的候選回答。"

        # 最終：請主 agent 根據整個討論產出最終答案，並一併輸出討論紀錄
        final_prompt = f"原始問題：\n{prompt}\n\n完整討論紀錄：\n"
        for speaker, text in discussion:
            final_prompt += f"{speaker}: {text}\n\n"
        final_prompt += "請根據上述討論給出清楚標示為「最終答案」的回覆，並補充可驗證的依據或步驟："

        final_result = await self.agent.run(final_prompt, message_history=message_history)
        final_answer = final_result.output
        # 儲存最後的 message history，供外層呼叫者（例如 CLI）使用
        try:
            self._last_messages = final_result.all_messages()
        except Exception:
            self._last_messages = None

        # 回傳包含討論過程與最終答案的內容，討論使用 <discussion> 標籤包起來，最終答案為純文字
        discussion_text = "\n".join([f"[{s}]\n{t}\n" for s, t in discussion])
        return f"<discussion>\n{discussion_text}\n</discussion>\n{final_answer}"

    async def run_stream(self, prompt: str, message_history: list[ModelRequest | ModelResponse] | None = None):
        """Streamed version of run(): yields chunks from philosopher/subagents/main agent as they produce output."""
        # decision
        consult = await self._should_consult_philosopher(prompt, message_history=message_history)
        if not consult:
            async with self.agent.run_stream(user_prompt=prompt, message_history=message_history) as result:
                async for chunk in result.stream_text(delta=True):
                    if not chunk:
                        continue
                    yield chunk
                try:
                    self._last_messages = result.all_messages()
                except Exception:
                    self._last_messages = None
            return

        # consult philosopher multi-round, streaming each step
        try:
            depth_choice = await self._decide_discussion_depth(prompt, message_history=message_history)
            depth_label = depth_choice.get("depth", "medium")
            max_rounds = int(depth_choice.get("rounds", 2))
        except Exception:
            depth_label = "medium"
            max_rounds = 2
        discussion: list[tuple[str, str]] = []
        current_prompt = prompt

        # start discussion wrapper for stream
        yield "<discussion>\n"

        for r in range(max_rounds):
            round_tag = f"回合 {r+1}"
            # philosopher analysis (stream)
            # 根據 depth_label 決定分析指示文字
            if depth_label == "very_shallow":
                depth_instr = "以極簡摘要回覆，只給出直接結論或最關鍵答案（一行或兩行）。"
            elif depth_label == "shallow":
                depth_instr = "以淺層重點式回覆，直接列出要點與最關鍵的不確定處。"
            elif depth_label == "deep":
                depth_instr = "以深度、逐步內省 (step-by-step) 方式分析，詳列不確定處、假設、證據、反駁與驗證步驟。"
            elif depth_label == "very_deep":
                depth_instr = "以非常深度、全面性的內省分析，提供詳細證據檢驗方法、替代觀點與潛在風險評估。"
            else:
                depth_instr = "以中等深度分析，列出主要不確定處、假設與建議的檢驗步驟。"

            # include available tools for philosopher to reference (stream flow)
            tools_meta = getattr(self.agent, "_registered_tools", None)
            if tools_meta:
                tools_lines = ["Available tools:"]
                for t in tools_meta:
                    sig = t.get("signature", "()")
                    doc = t.get("doc", "").splitlines()[0] if t.get("doc") else ""
                    tools_lines.append(f"- {t.get('name')}{sig}: {doc}")
                tools_text = "\n".join(tools_lines) + "\n\n"
            else:
                tools_text = "Available tools: (none)\n\n"
            sub_agents_text = self._format_sub_agents_context()

            phil_prompt = (
                f"{round_tag} - {depth_instr} Before analyzing, explicitly define the discussion scope: list what to focus on (Focus) and what is out of scope for this discussion (Out of scope).\n\n"
                + tools_text
                + sub_agents_text
                + "SUB-AGENTS: If any sub-agent is relevant, explicitly recommend which one(s) to consult by name.\n\n"
                + f"Then analyze the following question and list uncertainties, assumptions, and reasoning steps:\n\n{current_prompt}\n\n"
                "CONCISENESS RULES: Keep responses short and focused. First give a one-line Focus summary, then list up to 3 key uncertainties (bulleted), then a very short analysis (no more than 4 sentences)."
                "FACTS & TOOLS: If you require factual data or live information, produce a minimal 'execution_plan' JSON only (no long analysis) with the key 'plan' listing the necessary tool calls."
                "The Main Agent will execute that plan and return results for you to continue analysis. IMPORTANT: Only reference tools from the 'Available tools' list above and use exact tool names."
                " Each step object must have 'tool' (string matching an available tool name exactly), optional 'args' (object), and optional 'note' (string)."
                " Place the JSON on its own line so it can be parsed separately."
            )
            yield f"--- {round_tag} 哲學家分析開始 ---\n"
            collected_phil = ""
            try:
                if hasattr(self.philosopher, "run_stream"):
                    async for chunk in self.philosopher.run_stream(phil_prompt):
                        collected_phil += chunk
                        yield chunk
                else:
                    collected_phil = await self.philosopher.run(phil_prompt)
                    yield collected_phil
            except Exception:
                logger.exception("Philosopher co-agent failed during deliberation; breaking")
                break

            yield f"\n--- {round_tag} 哲學家分析結束 ---\n"
            discussion.append(("Philosopher", collected_phil))

            # detect & execute plan if present
            try:
                plan_obj = await self._extract_execution_plan(collected_phil)
                if plan_obj:
                    yield "--- Philosopher provided execution plan ---\n"
                    exec_results = await self.execute_plan(plan_obj)
                    for line in exec_results:
                        yield line + "\n"
                    discussion.append(("Execution", "\n".join(exec_results)))
                    # inform philosopher of execution results and stream their follow-up
                    exec_text = "\n".join(exec_results)
                    follow_prompt = (
                        "The main agent executed the plan and produced the following results:\n"
                        + exec_text
                        + "\n\nPlease update your analysis based on these results. If this changes focus or next steps, state them."
                    )
                    yield "--- Philosopher follow-up after execution ---\n"
                    collected_follow = ""
                    try:
                        if hasattr(self.philosopher, "run_stream"):
                            async for chunk in self.philosopher.run_stream(follow_prompt):
                                collected_follow += chunk
                                yield chunk
                        else:
                            collected_follow = await self.philosopher.run(follow_prompt)
                            yield collected_follow
                    except Exception:
                        logger.exception("Philosopher follow-up after execution failed (stream)")
                    yield "\n--- Philosopher follow-up end ---\n"
                    discussion.append(("Philosopher", collected_follow))
            except Exception:
                logger.exception("Failed to parse or execute philosopher plan (stream)")

            # 主 agent candidate answer (stream)
            main_input = f"原始問題：\n{prompt}\n\n討論紀錄：\n"
            for speaker, text in discussion:
                main_input += f"{speaker}: {text}\n\n"
            main_input += "請基於上述討論，提出一個候選回答（標註是否為最終結論）："

            yield f"--- MainAgent 候選回答（回合 {r+1}）開始 ---\n"
            collected_main = ""
            async with self.agent.run_stream(user_prompt=main_input, message_history=message_history) as mres:
                async for chunk in mres.stream_text(delta=True):
                    if not chunk:
                        continue
                    collected_main += chunk
                    yield chunk
            yield f"\n--- MainAgent 候選回答（回合 {r+1}）結束 ---\n"
            discussion.append(("MainAgent", collected_main))

            # philosopher critique (stream)
            critique_prompt = (
                "Review the Main Agent's candidate answer below. Point out errors, omissions, and suggestions for improvement,"
                " and indicate whether this can be considered the final conclusion. If yes, provide a clear 'Conclusion: ...'; otherwise, provide corrections and next steps:\n\n"
                + collected_main
                + "\n\nOriginal question:\n"
                + prompt
            )
            yield f"--- 哲學家評論（回合 {r+1}）開始 ---\n"
            collected_crit = ""
            try:
                if hasattr(self.philosopher, "run_stream"):
                    async for chunk in self.philosopher.run_stream(critique_prompt):
                        collected_crit += chunk
                        yield chunk
                else:
                    collected_crit = await self.philosopher.run(critique_prompt)
                    yield collected_crit
            except Exception:
                logger.exception("Philosopher co-agent failed during critique; breaking")
                break
            yield f"\n--- 哲學家評論（回合 {r+1}）結束 ---\n"
            discussion.append(("Philosopher", collected_crit))
            # 由主 agent 判斷是否要結束討論
            try:
                should_end = await self._should_end_discussion(
                    discussion, last_main_answer=collected_main, message_history=message_history
                )
            except Exception:
                should_end = False

            if should_end:
                break

            current_prompt = f"{prompt}\n\n哲學家回饋：\n{collected_crit}\n\n請根據回饋修正並提出新的候選回答。"

        # close discussion wrapper before final answer
        yield "</discussion>\n"

        # 最終答案（stream）
        final_prompt = f"原始問題：\n{prompt}\n\n完整討論紀錄：\n"
        for speaker, text in discussion:
            final_prompt += f"{speaker}: {text}\n\n"
        final_prompt += "請根據上述討論給出清楚標示為「最終答案」的回覆，並補充可驗證的依據或步驟："
        async with self.agent.run_stream(user_prompt=final_prompt, message_history=message_history) as fres:
            final_collected = ""
            async for chunk in fres.stream_text(delta=True):
                if not chunk:
                    continue
                final_collected += chunk
                yield chunk
            try:
                self._last_messages = fres.all_messages()
            except Exception:
                self._last_messages = None
