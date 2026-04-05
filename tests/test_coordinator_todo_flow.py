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
                "MISSING_REQUIREMENT: add API coverage",
                "SUSPECTED_PROBLEM: implementation skipped the API path",
                "REMEDIATION_TODO: add API coverage | update the API path and cover it with tests | high",
            ]
        ),
        task_id="t1",
    )

    assert verdict.verdict == "FAIL"
    assert verdict.missingRequirements == ["add API coverage"]
    assert verdict.suspectedProblems == ["implementation skipped the API path"]
    assert len(verdict.remediationTodos) == 1
    assert verdict.remediationTodos[0].title == "add API coverage"


def test_parse_verification_verdict_missing_verdict_falls_back_to_fail():
    verdict = parse_verification_verdict("missing any explicit verdict", task_id="t-missing")

    assert verdict.verdict == "FAIL"
    assert verdict.summary
    assert verdict.remediationTodos


def test_coordinator_validation_failure_generates_remediation_todo_and_retries():
    async def scenario() -> str:
        state = {"worker_calls": 0, "verify_calls": 0}

        async def make_or_update_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
            title = "initial-task"
            instruction = "implement the initial change"
            if "[Validation remediation]" in ctx.userRequest:
                title = "remediation-task"
                instruction = "fix the missing remediation item"
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
                result=f"completed:{spec.instruction}",
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
                            "MISSING_REQUIREMENT: add remediation",
                            "REMEDIATION_TODO: add remediation | fix the missing remediation item | high",
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
            CoordinatorTurnContext(userRequest="implement the feature", taskKind="implementation"),
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
                workerSpecs=[
                    SpawnWorkerInput(
                        agentType="implementation",
                        title="snapshot-task-1",
                        originalUserRequest=ctx.userRequest,
                        instruction="snapshot 1",
                        runInBackground=False,
                    ),
                    SpawnWorkerInput(
                        agentType="implementation",
                        title="snapshot-task-2",
                        originalUserRequest=ctx.userRequest,
                        instruction="snapshot 2",
                        runInBackground=False,
                    ),
                ],
            )

        async def spawn_worker(spec: SpawnWorkerInput) -> WorkerResult:
            return WorkerResult(
                taskId=f"task-{spec.title}",
                status="completed",
                summary=spec.title,
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
            CoordinatorTurnContext(userRequest="implement snapshot flow", taskKind="implementation"),
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


def test_single_worker_fast_path_skips_planning_snapshot():
    async def scenario() -> list[str]:
        snapshots: list[str] = []

        async def make_or_update_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
            return CoordinatorPlan(
                type="spawn-worker",
                workerSpec=SpawnWorkerInput(
                    agentType="implementation",
                    title="single-task",
                    originalUserRequest=ctx.userRequest,
                    instruction="fix it",
                    runInBackground=False,
                ),
            )

        async def spawn_worker(_spec: SpawnWorkerInput) -> WorkerResult:
            return WorkerResult(
                taskId="task-1",
                status="completed",
                summary="single-task",
                result="done",
                filesChanged=[],
                commandsExecuted=[],
                evidence=["test evidence"],
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
            CoordinatorTurnContext(userRequest="fix it", taskKind="implementation"),
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
    assert not any("[TODO] phase=planning" in item for item in snapshots)
    assert any("[TODO] phase=executing" in item for item in snapshots)
    assert any("[TODO] phase=completed" in item for item in snapshots)


def test_research_worker_skips_verification():
    async def scenario() -> str:
        async def make_or_update_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
            return CoordinatorPlan(
                type="spawn-worker",
                workerSpec=SpawnWorkerInput(
                    agentType="research",
                    title="research-task",
                    originalUserRequest=ctx.userRequest,
                    instruction="collect answer",
                    runInBackground=False,
                ),
            )

        async def spawn_worker(_spec: SpawnWorkerInput) -> WorkerResult:
            return WorkerResult(
                taskId="task-1",
                status="completed",
                summary="research-task",
                result="answer",
                filesChanged=[],
                commandsExecuted=[],
                evidence=["source"],
                unresolvedIssues=[],
                usage=TaskUsage(durationMs=1),
            )

        async def spawn_verification_worker(_input) -> VerificationResult:
            raise AssertionError("research fast path should not verify")

        def synthesize_final_answer(_ctx, worker, verification):
            return f"{worker.summary}|{verification.verdict if verification else 'NONE'}"

        def augment_context_with_failure(ctx, _worker, _verification):
            return ctx

        return await run_coordinator_turn(
            CoordinatorTurnContext(userRequest="research this", taskKind="research"),
            make_or_update_plan=make_or_update_plan,
            spawn_worker=spawn_worker,
            spawn_verification_worker=spawn_verification_worker,
            synthesize_final_answer=synthesize_final_answer,
            augment_context_with_failure=augment_context_with_failure,
        )

    result = asyncio.run(scenario())
    assert result == "research-task|NONE"


def test_coordinator_stops_on_repeated_identical_remediation_todos():
    async def scenario() -> str:
        async def make_or_update_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
            title = "research-task"
            if "[Validation remediation]" in ctx.userRequest:
                title = "remediation-task"
            return CoordinatorPlan(
                type="spawn-worker",
                workerSpec=SpawnWorkerInput(
                    agentType="research",
                    title=title,
                    originalUserRequest=ctx.userRequest,
                    instruction="collect evidence",
                    runInBackground=False,
                ),
            )

        async def spawn_worker(spec: SpawnWorkerInput) -> WorkerResult:
            return WorkerResult(
                taskId=f"task-{spec.title}",
                status="completed",
                summary=spec.title,
                result="evidence collected",
                filesChanged=[],
                commandsExecuted=[],
                evidence=[],
                unresolvedIssues=[],
                usage=TaskUsage(durationMs=5),
            )

        async def spawn_verification_worker(_input) -> VerificationResult:
            return parse_verification_verdict(
                "\n".join(
                    [
                        "VERDICT: FAIL",
                        "REMEDIATION_TODO: add more evidence | collect more evidence | high",
                    ]
                ),
                task_id="verify-loop",
            )

        def synthesize_final_answer(_ctx, worker, verification):
            verdict = verification.verdict if verification else "NONE"
            return f"{worker.summary}|{verdict}"

        def augment_context_with_failure(ctx, _worker, _verification):
            return ctx

        return await run_coordinator_turn(
            CoordinatorTurnContext(userRequest="research the issue", taskKind="research"),
            make_or_update_plan=make_or_update_plan,
            spawn_worker=spawn_worker,
            spawn_verification_worker=spawn_verification_worker,
            synthesize_final_answer=synthesize_final_answer,
            augment_context_with_failure=augment_context_with_failure,
        )

    result = asyncio.run(scenario())
    assert result == "research-task|NONE"


def test_validation_failure_without_remediation_finalizes_instead_of_blocking():
    async def scenario() -> str:
        async def make_or_update_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
            return CoordinatorPlan(
                type="spawn-worker",
                workerSpec=SpawnWorkerInput(
                    agentType="implementation",
                    title="impl-task",
                    originalUserRequest=ctx.userRequest,
                    instruction="ship change",
                    runInBackground=False,
                ),
            )

        async def spawn_worker(_spec: SpawnWorkerInput) -> WorkerResult:
            return WorkerResult(
                taskId="task-1",
                status="completed",
                summary="impl-task",
                result="done",
                filesChanged=["app.py"],
                commandsExecuted=["pytest"],
                evidence=["pytest failed"],
                unresolvedIssues=[],
                usage=TaskUsage(durationMs=1),
            )

        async def spawn_verification_worker(_input) -> VerificationResult:
            return parse_verification_verdict("VERDICT: FAIL", task_id="verify-1")

        def synthesize_final_answer(_ctx, worker, verification):
            return f"{worker.summary}|{verification.verdict if verification else 'NONE'}"

        def augment_context_with_failure(ctx, _worker, _verification):
            return ctx

        return await run_coordinator_turn(
            CoordinatorTurnContext(userRequest="implement it", taskKind="implementation"),
            make_or_update_plan=make_or_update_plan,
            spawn_worker=spawn_worker,
            spawn_verification_worker=spawn_verification_worker,
            synthesize_final_answer=synthesize_final_answer,
            augment_context_with_failure=augment_context_with_failure,
        )

    result = asyncio.run(scenario())
    assert result.endswith("|FAIL")


def test_validation_remediation_is_limited_to_one_retry():
    async def scenario() -> tuple[str, int, int]:
        state = {"worker_calls": 0, "verify_calls": 0}

        async def make_or_update_plan(ctx: CoordinatorTurnContext) -> CoordinatorPlan:
            title = "initial-task"
            instruction = "do initial task"
            if "[Validation remediation]" in ctx.userRequest:
                title = "remediation-task"
                instruction = "apply remediation"
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
                result=spec.instruction,
                filesChanged=["app.py"],
                commandsExecuted=["pytest"],
                evidence=[f"evidence-{state['worker_calls']}"],
                unresolvedIssues=[],
                usage=TaskUsage(durationMs=1),
            )

        async def spawn_verification_worker(_input) -> VerificationResult:
            state["verify_calls"] += 1
            if state["verify_calls"] == 1:
                return parse_verification_verdict(
                    "\n".join(
                        [
                            "VERDICT: FAIL",
                            "REMEDIATION_TODO: write missing test | add the missing test | high",
                        ]
                    ),
                    task_id="verify-1",
                )
            return parse_verification_verdict("VERDICT: FAIL", task_id="verify-2")

        def synthesize_final_answer(_ctx, worker, verification):
            return f"{worker.summary}|{verification.verdict if verification else 'NONE'}"

        def augment_context_with_failure(ctx, _worker, _verification):
            return ctx

        result = await run_coordinator_turn(
            CoordinatorTurnContext(userRequest="implement it", taskKind="implementation"),
            make_or_update_plan=make_or_update_plan,
            spawn_worker=spawn_worker,
            spawn_verification_worker=spawn_verification_worker,
            synthesize_final_answer=synthesize_final_answer,
            augment_context_with_failure=augment_context_with_failure,
        )
        return result, state["worker_calls"], state["verify_calls"]

    result, worker_calls, verify_calls = asyncio.run(scenario())
    assert result.endswith("|FAIL")
    assert worker_calls == 2
    assert verify_calls == 2
