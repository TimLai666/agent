from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable

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
from internal.core.tasks.task_types import TaskUsage, VerificationResult, WorkerResult
from internal.services.subagent_tasks import AgentToolInput


@dataclass
class OrchestrationRuntime:
    main_agent: object
    on_todo_update: Callable[[str], None] | None = None

    async def handle_user_turn(
        self,
        user_prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> str:
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
            on_todo_update=self.on_todo_update,
        )

    async def handle_user_turn_stream(
        self,
        user_prompt: str,
        message_history: list[ModelRequest | ModelResponse] | None = None,
    ) -> AsyncIterator[str]:
        task = asyncio.create_task(
            self.handle_user_turn(user_prompt, message_history=message_history)
        )
        while not task.done():
            await asyncio.sleep(2)

        result = await task
        if result:
            yield result

    async def _make_or_update_plan(self, ctx: CoordinatorTurnContext) -> CoordinatorPlan:
        if ctx.taskKind in {"question", "research"} and self._looks_like_direct_question(ctx.userRequest):
            answer = await self.main_agent._execute_turn_core(ctx.userRequest)
            return CoordinatorPlan(type="answer-directly", finalAnswer=answer)

        worker_type = "implementation" if ctx.taskKind in {"implementation", "bugfix", "infra"} else "research"

        if self._should_run_background(ctx.userRequest):
            payload = AgentToolInput(
                prompt=ctx.userRequest,
                name=f"{worker_type}-task",
                subagent_type=worker_type,
                run_in_background=True,
            )
            created = await self.main_agent._task_manager.spawnAgentTask(
                payload,
                self.main_agent._session_id,
            )
            task_id = created.get("task_id", "")
            return CoordinatorPlan(
                type="answer-directly",
                finalAnswer=(
                    "已建立背景 subagent 任務，主流程先回覆你目前進度。\n"
                    f"- task_id: {task_id}\n"
                    f"- worker: {worker_type}\n"
                    "可用 ListSubagentTasks 查狀態；完成後結果會在下一輪自動帶入。"
                ),
            )

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

        # Prefer task-notification transport, but allow task-state fallback to avoid hard failure.
        notification = self._find_task_notification(task.id)
        if notification:
            parsed = parse_task_notification_xml(notification)
            parsed.evidence = list(task.evidence)
            parsed.unresolvedIssues = list(task.unresolvedIssues)
            return parsed

        status = task.status if task.status in {"completed", "failed", "killed"} else "failed"
        return WorkerResult(
            taskId=task.id,
            status=status,
            summary=task.summary or "",
            result=task.result or "",
            filesChanged=list(task.filesChanged),
            commandsExecuted=list(task.commandsExecuted),
            evidence=list(task.evidence),
            unresolvedIssues=list(task.unresolvedIssues),
            usage=TaskUsage(durationMs=task.durationMs),
        )

    def _find_task_notification(self, task_id: str) -> str | None:
        notifications = getattr(self.main_agent, "_task_notifications", []) or []
        for notification in reversed(notifications):
            try:
                parsed = parse_task_notification_xml(notification)
            except Exception:
                continue
            if parsed.taskId == task_id:
                return notification
        return None

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

    def _should_run_background(self, prompt: str) -> bool:
        lowered = prompt.lower()
        hints = [
            "背景",
            "background",
            "先回覆",
            "先回答",
            "稍後給我",
            "不要等",
            "不用等",
            "asynchronous",
            "async",
        ]
        return any(hint in lowered for hint in hints)


def create_runtime(
    main_agent: object,
    on_todo_update: Callable[[str], None] | None = None,
) -> OrchestrationRuntime:
    return OrchestrationRuntime(main_agent=main_agent, on_todo_update=on_todo_update)


async def handle_user_turn(
    user_prompt: str,
    main_agent: object,
    message_history: list[ModelRequest | ModelResponse] | None = None,
) -> str:
    runtime = create_runtime(main_agent)
    return await runtime.handle_user_turn(user_prompt, message_history=message_history)
