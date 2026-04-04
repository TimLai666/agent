import asyncio

from internal.core.agents.agent_types import SpawnWorkerInput
from internal.core.coordinator.coordinator_loop import (
    CoordinatorPlan,
    CoordinatorTurnContext,
    run_coordinator_turn,
)
from internal.core.protocol.verdict_parser import parse_verification_verdict
from internal.core.tasks.task_types import TaskUsage, VerificationResult, WorkerResult


def test_parse_verification_verdict_extracts_remediation_todo():
    verdict = parse_verification_verdict(
        "\n".join(
            [
                "VERDICT: FAIL",
                "MISSING_REQUIREMENT: 缺少 API 驗證",
                "SUSPECTED_PROBLEM: 尚未執行整合測試",
                "REMEDIATION_TODO: 補 API 驗證 | 新增整合測試與結果證據 | high",
            ]
        ),
        task_id="t1",
    )

    assert verdict.verdict == "FAIL"
    assert verdict.missingRequirements == ["缺少 API 驗證"]
    assert verdict.suspectedProblems == ["尚未執行整合測試"]
    assert len(verdict.remediationTodos) == 1
    assert verdict.remediationTodos[0].title == "補 API 驗證"


def test_coordinator_validation_failure_generates_remediation_todo_and_retries():
    async def scenario() -> str:
        state = {"worker_calls": 0, "verify_calls": 0}

        async def make_or_update_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
            title = "initial-task"
            instruction = "完成初始任務"
            if "[Validation remediation]" in ctx.userRequest:
                title = "remediation-task"
                instruction = "修補驗證缺漏"
            return CoordinatorPlan(
                type="spawn-worker",
                workerSpec=SpawnWorkerInput(
                    agentType="implementation",
                    title=title,
                    originalUserRequest=ctx.userRequest,
                    instruction=instruction,
                    runInBackground=False,
                ),
            )

        async def spawn_worker(spec: SpawnWorkerInput) -> WorkerResult:
            state["worker_calls"] += 1
            return WorkerResult(
                taskId=f"task-{state['worker_calls']}",
                status="completed",
                summary=spec.title,
                result=f"已完成 {spec.instruction}",
                filesChanged=[],
                commandsExecuted=[],
                evidence=[f"evidence-{state['worker_calls']}"],
                unresolvedIssues=[],
                usage=TaskUsage(durationMs=10),
            )

        async def spawn_verification_worker(_input) -> VerificationResult:
            state["verify_calls"] += 1
            if state["verify_calls"] == 1:
                return parse_verification_verdict(
                    "\n".join(
                        [
                            "VERDICT: FAIL",
                            "MISSING_REQUIREMENT: 缺少 remediation",
                            "REMEDIATION_TODO: 補驗證缺漏 | 補上驗證缺漏並重新驗證 | high",
                        ]
                    ),
                    task_id="verify-1",
                )
            return parse_verification_verdict("VERDICT: PASS", task_id="verify-2")

        def synthesize_final_answer(_ctx, worker, verification):
            return f"{worker.summary}|{verification.verdict if verification else 'NONE'}"

        def augment_context_with_failure(ctx, _worker, _verification):
            return ctx

        return await run_coordinator_turn(
            CoordinatorTurnContext(userRequest="請完成任務", taskKind="implementation"),
            make_or_update_plan=make_or_update_plan,
            spawn_worker=spawn_worker,
            spawn_verification_worker=spawn_verification_worker,
            synthesize_final_answer=synthesize_final_answer,
            augment_context_with_failure=augment_context_with_failure,
        )

    result = asyncio.run(scenario())
    assert result.endswith("|PASS")


def test_coordinator_emits_todo_snapshots():
    async def scenario() -> list[str]:
        snapshots: list[str] = []

        async def make_or_update_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
            return CoordinatorPlan(
                type="spawn-worker",
                workerSpec=SpawnWorkerInput(
                    agentType="implementation",
                    title="snapshot-task",
                    originalUserRequest=ctx.userRequest,
                    instruction="執行 snapshot",
                    runInBackground=False,
                ),
            )

        async def spawn_worker(_spec: SpawnWorkerInput) -> WorkerResult:
            return WorkerResult(
                taskId="task-1",
                status="completed",
                summary="snapshot-task",
                result="done",
                filesChanged=[],
                commandsExecuted=[],
                evidence=[],
                unresolvedIssues=[],
                usage=TaskUsage(durationMs=1),
            )

        async def spawn_verification_worker(_input) -> VerificationResult:
            return parse_verification_verdict("VERDICT: PASS", task_id="verify-1")

        def synthesize_final_answer(_ctx, worker, verification):
            return f"{worker.summary}|{verification.verdict if verification else 'NONE'}"

        def augment_context_with_failure(ctx, _worker, _verification):
            return ctx

        await run_coordinator_turn(
            CoordinatorTurnContext(userRequest="請完成任務", taskKind="implementation"),
            make_or_update_plan=make_or_update_plan,
            spawn_worker=spawn_worker,
            spawn_verification_worker=spawn_verification_worker,
            synthesize_final_answer=synthesize_final_answer,
            augment_context_with_failure=augment_context_with_failure,
            on_todo_update=lambda text: snapshots.append(text),
        )
        return snapshots

    snapshots = asyncio.run(scenario())
    assert snapshots
    assert any("[TODO] phase=planning" in item for item in snapshots)
    assert any("[TODO] phase=completed" in item for item in snapshots)
