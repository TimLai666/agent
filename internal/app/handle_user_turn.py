from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace

from pydantic_ai.messages import ModelRequest, ModelResponse

from internal.core.agents.agent_types import SpawnVerificationInput, SpawnWorkerInput
from internal.core.coordinator.coordinator_loop import (
    CoordinatorPlan,
    CoordinatorTurnContext,
    run_coordinator_turn,
)
from internal.core.coordinator.result_synthesizer import synthesize_final_answer
from internal.core.protocol.task_notification import parse_task_notification_xml
from internal.core.protocol.verdict_parser import parse_verification_verdict
from internal.core.tasks.task_types import VerificationResult, WorkerResult
from internal.services.subagent_tasks import AgentToolInput

from internal.core.session.session_mode import resolve_session_mode


@dataclass
class OrchestrationRuntime:
    main_agent: object

    async def handle_user_turn(
        self,
        user_prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
        mode = resolve_session_mode(user_prompt)
        if mode == "normal":
            return await self.main_agent._execute_turn_core(user_prompt, message_history=message_history)

        ctx = CoordinatorTurnContext(
            userRequest=user_prompt,
            taskKind=self._infer_task_kind(user_prompt),
        )

        return await run_coordinator_turn(
            ctx,
            make_or_update_plan=self._make_or_update_plan,
            spawn_worker=self._spawn_worker,
            spawn_verification_worker=self._spawn_verification,
            synthesize_final_answer=lambda context, worker, verification: synthesize_final_answer(
                worker, verification
            ),
            augment_context_with_failure=self._augment_context_with_failure,
        )

    async def handle_user_turn_stream(
        self,
        user_prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> AsyncIterator[str]:
        mode = resolve_session_mode(user_prompt)
        if mode == "normal":
            async for chunk in self.main_agent._execute_turn_stream_core(
                user_prompt,
                message_history=message_history,
            ):
                yield chunk
            return

        yield "\n[進度] coordinator mode 啟動，正在規劃任務...\n"
        task = asyncio.create_task(
            self.handle_user_turn(user_prompt, message_history=message_history)
        )
        heartbeat_index = 0
        heartbeat_messages = (
            "[進度] 正在執行 worker 任務...",
            "[進度] 正在驗證結果與彙整回覆...",
        )
        while not task.done():
            await asyncio.sleep(2)
            if task.done():
                break
            yield heartbeat_messages[heartbeat_index % len(heartbeat_messages)] + "\n"
            heartbeat_index += 1

        result = await task
        if result:
            yield result

    async def _make_or_update_plan(self, ctx: CoordinatorTurnContext) -> CoordinatorPlan:
        if ctx.taskKind in {"question", "research"} and self._looks_like_direct_question(ctx.userRequest):
            answer = await self.main_agent._execute_turn_core(ctx.userRequest)
            return CoordinatorPlan(type="answer-directly", finalAnswer=answer)

        worker_type = "implementation" if ctx.taskKind in {"implementation", "bugfix", "infra"} else "research"
        return CoordinatorPlan(
            type="spawn-worker",
            workerSpec=SpawnWorkerInput(
                agentType=worker_type,
                title=f"{worker_type}-task",
                originalUserRequest=ctx.userRequest,
                instruction=ctx.userRequest,
                runInBackground=False,
            ),
        )

    async def _spawn_worker(self, spec: SpawnWorkerInput) -> WorkerResult:
        subagent_type = spec.agentType if spec.agentType != "general-purpose" else ""
        payload = AgentToolInput(
            prompt=spec.instruction,
            name=spec.title,
            subagent_type=subagent_type,
            run_in_background=False,
            model=spec.model,
        )
        created = await self.main_agent._task_manager.spawnAgentTask(payload, self.main_agent._session_id)
        task = self.main_agent._task_manager.registry.getTask(created["task_id"])
        if task is None:
            raise RuntimeError("Task not found after worker completion")

        # Use task-notification as the canonical transport format inside coordinator flow.
        if not self.main_agent._task_notifications:
            raise RuntimeError("Missing task notification from worker run")
        notification = self.main_agent._task_notifications[-1]
        parsed = parse_task_notification_xml(notification)
        parsed.evidence = list(task.evidence)
        parsed.unresolvedIssues = list(task.unresolvedIssues)
        return parsed

    async def _spawn_verification(self, input_data: SpawnVerificationInput) -> VerificationResult:
        verification_task = SimpleNamespace(subagentType="verification", mode="spawn")
        prompt = (
            "ORIGINAL USER REQUEST:\n"
            f"{input_data.originalUserRequest}\n\n"
            "WORKER SUMMARY:\n"
            f"{input_data.workerResult.summary}\n\n"
            "FILES CHANGED:\n"
            + "\n".join(input_data.filesChanged)
            + "\n\n"
            "COMMANDS ALREADY RUN:\n"
            + "\n".join(input_data.workerResult.commandsExecuted)
            + "\n\n"
            "CLAIMS TO VERIFY:\n"
            + input_data.workerResult.result
        )
        output = await self.main_agent._run_subagent_task(verification_task, prompt)
        return parse_verification_verdict(output, task_id=input_data.workerResult.taskId)

    def _augment_context_with_failure(
        self,
        ctx: CoordinatorTurnContext,
        worker: WorkerResult,
        verification: VerificationResult | None,
    ) -> CoordinatorTurnContext:
        details = [ctx.userRequest, worker.summary]
        if verification:
            details.append(f"verification={verification.verdict}")
            if verification.suspectedProblems:
                details.extend(verification.suspectedProblems)
        return CoordinatorTurnContext(
            userRequest="\n".join(details),
            taskKind="implementation",
        )

    def _infer_task_kind(self, prompt: str) -> str:
        lowered = prompt.lower()
        if any(token in lowered for token in ["fix", "bug", "修", "錯誤"]):
            return "bugfix"
        if any(token in lowered for token in ["implement", "build", "新增", "實作", "重構"]):
            return "implementation"
        if any(token in lowered for token in ["infra", "deploy", "ci", "cd", "k8s"]):
            return "infra"
        if any(token in lowered for token in ["research", "investigate", "分析", "找"]):
            return "research"
        return "question"

    def _looks_like_direct_question(self, prompt: str) -> bool:
        lowered = prompt.lower().strip()
        if lowered.endswith("?") or lowered.endswith("？"):
            return True
        direct_tokens = ["是什麼", "what is", "how does", "怎麼"]
        return any(token in lowered for token in direct_tokens)


def create_runtime(main_agent: object) -> OrchestrationRuntime:
    return OrchestrationRuntime(main_agent=main_agent)


async def handle_user_turn(
    user_prompt: str,
    main_agent: object,
    message_history: list[ModelRequest | ModelResponse] | None = None,
) -> str:
    runtime = create_runtime(main_agent)
    return await runtime.handle_user_turn(user_prompt, message_history=message_history)
