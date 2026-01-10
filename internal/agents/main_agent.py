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
from internal.sub_agents.base import SubAgent

PROMPT_KEY = "MAIN_AGENT_PROMPT"
ENV_PREFIX = "MAIN"


class MainAgent:
    PROMPT_KEY = PROMPT_KEY
    ENV_PREFIX = ENV_PREFIX

    @classmethod
    def create(
        cls,
        base_config: AgentConfig,
        env: dict[str, str],
        http_client: AsyncClient,
        philosopher: PhilosopherCoAgent,
        sub_agent: SubAgent,
    ) -> "MainAgent":
        config = load_agent_config_chain([cls.ENV_PREFIX], base_config, env)
        model = create_openai_model(config, http_client)
        agent: Agent[None, str] = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            instructions=get_prompt(cls.PROMPT_KEY),
            tools=[],
            model_settings={"temperature": config.temperature},
        )
        return cls(agent, philosopher, sub_agent)

    def __init__(
        self,
        agent: Agent[None, str],
        philosopher: PhilosopherCoAgent,
        sub_agent: SubAgent,
    ) -> None:
        self.agent = agent
        self.philosopher = philosopher
        self.sub_agent = sub_agent
        self._last_messages: list[ModelRequest | ModelResponse] | None = None
        # register tool functions so agent can call them; defining as methods
        try:
            # calling tool_plain with the bound method registers it
            self.agent.tool_plain(self.ask_philosopher)
            self.agent.tool_plain(self.delegate_to_subagent)
        except Exception:
            # registration failures shouldn't break initialization
            logger.debug("Tool registration skipped or failed during init")

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
            " 僅回傳一個有效 JSON 對象，不要包含其他文字。JSON 格式：{'consult': true/false, 'reason': '短理由'}。"
            " 範例：\n"
            "輸入: '現在幾點'\n輸出: {" + '"consult": false, "reason": "簡單事實性查詢"}' + "\n"
            "輸入: '評估不同投資組合的風險與報酬'\n輸出: {" + '"consult": true, "reason": "需要權衡與推理"}' + "\n\n"
            "使用者輸入：\n" + prompt + "\n\n請只回傳 JSON："
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

    async def delegate_to_subagent(self, task: str) -> str:
        """Tool: delegate execution to sub-agent."""
        subagent_name = type(self.sub_agent).__name__
        logger.info("Main agent -> subagent (%s): %s", subagent_name, task)
        print(f"[LOG] main -> subagent({subagent_name}): {task}")
        if hasattr(self.sub_agent, "run_stream"):
            collected = ""
            async for chunk in self.sub_agent.run_stream(task):
                collected += chunk
            return collected
        return await self.sub_agent.run(task)

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
            return result.output

        # 多輪討論流程：主 agent 與哲學家 co-agent 一來一回討論，直到哲學家表示可作為結論或達到最大輪數
        max_rounds = 3
        discussion: list[tuple[str, str]] = []
        current_prompt = prompt

        for r in range(max_rounds):
            round_tag = f"回合 {r+1}"
            # 向哲學家請求分析/內省
            try:
                phil_prompt = (
                    f"{round_tag} - 請以內省（step-by-step）方式分析下列問題，列出不確定處、假設與判斷依據：\n\n{current_prompt}"
                )
                logger.info("Main agent requesting philosopher analysis (round %d)", r + 1)
                print(f"[LOG] main -> philosopher (deliberation) round {r+1}")
                phil_resp = await self.philosopher.run(phil_prompt)
            except Exception:
                logger.exception("Philosopher co-agent failed during deliberation; breaking")
                break

            discussion.append(("Philosopher", phil_resp))

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
                    "請檢視以下主 agent 的候選回答，指出錯誤、遺漏與改進建議，"
                    "並說明是否可以作為最終結論；若可以，請以「結論：...」明確給出；否則請提供修正方向：\n\n"
                    + main_answer
                    + "\n\n原始問題：\n"
                    + prompt
                )
                print(f"[LOG] main -> philosopher (critique) round {r+1}")
                phil_crit = await self.philosopher.run(critique_prompt)
            except Exception:
                logger.exception("Philosopher co-agent failed during critique; breaking")
                break

            discussion.append(("Philosopher", phil_crit))

            # 終止條件：哲學家回應明確包含「結論」字眼或表示同意
            lower = phil_crit.lower()
            if "結論" in phil_crit or "可以作為最終" in lower or "最終結論" in lower or "conclusion" in lower:
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
        max_rounds = 3
        discussion: list[tuple[str, str]] = []
        current_prompt = prompt

        # start discussion wrapper for stream
        yield "<discussion>\n"

        for r in range(max_rounds):
            round_tag = f"回合 {r+1}"
            # philosopher analysis (stream)
            phil_prompt = (
                f"{round_tag} - 請以內省（step-by-step）方式分析下列問題，列出不確定處、假設與判斷依據：\n\n{current_prompt}"
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
                "請檢視以下主 agent 的候選回答，指出錯誤、遺漏與改進建議，"
                "並說明是否可以作為最終結論；若可以，請以「結論：...」明確給出；否則請提供修正方向：\n\n"
                + collected_main
                + "\n\n原始問題：\n"
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

            lower = collected_crit.lower()
            if "結論" in collected_crit or "可以作為最終" in lower or "最終結論" in lower or "conclusion" in lower:
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
