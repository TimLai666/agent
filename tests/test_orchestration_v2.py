import asyncio
from pathlib import Path

from internal.core.orchestration.runtime import OrchestrationRuntime
from internal.core.orchestration.store import OrchestrationStore
from internal.core.orchestration.types import (
    CheckpointPayload,
    RecoveryPolicy,
    StepContract,
    StepExecutionResult,
    StepSpec,
    TaskGraphPlan,
    VerificationEvidenceItem,
    VerificationReport,
)


def _contract(done_when: str = "done") -> StepContract:
    return StepContract(
        doneWhen=done_when,
        mustProduce=["summary"],
        mustNotChange=[],
        requiredChecks=[],
        evidenceShape=["summary"],
        repairHint="retry with narrower scope",
    )


def _policy(max_attempts: int = 2) -> RecoveryPolicy:
    return RecoveryPolicy(
        maxAttempts=max_attempts,
        onTransient="retry-step",
        onDeterministic="create-repair-step",
        onDependency="wait-dependency",
        onUserDecision="wait-user",
        onSystemCrash="resume-from-checkpoint",
    )


def _step(
    step_id: str,
    *,
    kind: str,
    goal: str,
    depends_on: list[str] | None = None,
    verification_mode: str = "none",
) -> StepSpec:
    return StepSpec(
        stepId=step_id,
        kind=kind,
        goal=goal,
        dependsOn=depends_on or [],
        executor="worker",
        inputs={"goal": goal},
        contract=_contract(goal),
        verificationMode=verification_mode,
        retryPolicy=_policy(),
        recoveryPoint=f"checkpoint:{step_id}",
    )


def test_store_persists_task_plan_artifacts_and_checkpoints(tmp_path: Path):
    store = OrchestrationStore(tmp_path / "orchestration.db")
    plan = TaskGraphPlan(
        taskKind="implementation",
        steps=[
            _step("discover_repo", kind="discover", goal="inspect repo"),
            _step("implement_fix", kind="implement", goal="fix bug", depends_on=["discover_repo"]),
        ],
    )

    task_run = store.create_task_run(
        session_id="session-1",
        user_request="fix the bug",
        task_kind="implementation",
        plan=plan,
    )

    steps = store.list_steps(task_run.taskRunId)
    assert [step.stepId for step in steps] == ["discover_repo", "implement_fix"]
    assert steps[0].status == "ready"
    assert steps[1].status == "waiting_dependency"

    artifact = store.append_step_artifact(
        steps[0].stepRunId,
        artifact_type="worker_result",
        payload={"summary": "repo inspected"},
        summary="inspection summary",
        created_by="worker",
    )
    checkpoint = store.commit_checkpoint(
        steps[0].stepRunId,
        CheckpointPayload(
            recoveryPoint="checkpoint:discover_repo",
            summary="discover done",
            artifactRefs=[artifact.artifactId],
            data={"files": ["README.md"]},
        ),
    )

    updated = store.transition_step(
        steps[0].stepRunId,
        from_status="ready",
        to_status="completed",
        summary="discover complete",
        last_checkpoint_id=checkpoint.checkpointId,
    )
    assert updated.status == "completed"

    refreshed = store.get_step_run(steps[0].stepRunId)
    assert refreshed is not None
    assert refreshed.lastCheckpointId == checkpoint.checkpointId
    assert refreshed.summary == "discover complete"


def test_runtime_parallelizes_discover_and_serializes_writer(tmp_path: Path):
    store = OrchestrationStore(tmp_path / "runtime.db")
    plan = TaskGraphPlan(
        taskKind="implementation",
        steps=[
            _step("discover_a", kind="discover", goal="inspect A"),
            _step("discover_b", kind="discover", goal="inspect B"),
            _step("implement_a", kind="implement", goal="edit A", depends_on=["discover_a", "discover_b"]),
            _step("implement_b", kind="implement", goal="edit B", depends_on=["discover_a", "discover_b"]),
            _step("synthesize", kind="synthesize", goal="final answer", depends_on=["implement_a", "implement_b"]),
        ],
    )

    active_discover = 0
    max_discover = 0
    active_writer = 0
    max_writer = 0

    async def plan_builder(task_kind: str, user_request: str) -> TaskGraphPlan:
        assert task_kind == "implementation"
        assert user_request == "do the work"
        return plan

    async def execute_step(step: StepSpec, upstream_artifacts):
        nonlocal active_discover, max_discover, active_writer, max_writer
        if step.kind == "discover":
            active_discover += 1
            max_discover = max(max_discover, active_discover)
            await asyncio.sleep(0.02)
            active_discover -= 1
            return StepExecutionResult(
                status="completed",
                summary=f"{step.stepId} done",
                result=step.goal,
                evidence=[step.stepId],
            )
        if step.kind == "implement":
            active_writer += 1
            max_writer = max(max_writer, active_writer)
            assert len(upstream_artifacts) >= 2
            await asyncio.sleep(0.01)
            active_writer -= 1
            return StepExecutionResult(
                status="completed",
                summary=f"{step.stepId} done",
                result=step.goal,
                filesChanged=[f"{step.stepId}.py"],
                evidence=[step.stepId],
            )
        return StepExecutionResult(
            status="completed",
            summary="all done",
            result="final answer",
            evidence=["synthesis"],
        )

    async def verify_step(step: StepSpec, upstream_artifacts):
        return VerificationReport(
            verdict="PASS",
            summary=f"{step.stepId} verified",
            checkedItems=["shape"],
            failedItems=[],
            evidence=[VerificationEvidenceItem(name="shape", result="PASS", detail="ok")],
            remediationSteps=[],
            confidence=0.9,
            requiresUserInput=False,
        )

    runtime = OrchestrationRuntime(
        store=store,
        plan_builder=plan_builder,
        step_executor=execute_step,
        verification_executor=verify_step,
    )

    result = asyncio.run(runtime.execute("session-1", "do the work", "implementation"))

    assert result == "final answer"
    assert max_discover >= 2
    assert max_writer == 1


def test_runtime_turns_verification_failure_into_repair_step(tmp_path: Path):
    store = OrchestrationStore(tmp_path / "repair.db")
    plan = TaskGraphPlan(
        taskKind="bugfix",
        steps=[
            _step("implement_fix", kind="implement", goal="ship fix", verification_mode="independent"),
            _step("verify_fix", kind="verify", goal="verify fix", depends_on=["implement_fix"], verification_mode="independent"),
            _step("synthesize", kind="synthesize", goal="answer", depends_on=["verify_fix"]),
        ],
    )

    verifier_calls = 0

    async def plan_builder(task_kind: str, user_request: str) -> TaskGraphPlan:
        return plan

    async def execute_step(step: StepSpec, upstream_artifacts):
        return StepExecutionResult(
            status="completed",
            summary=f"{step.stepId} complete",
            result=step.goal,
            filesChanged=[f"{step.stepId}.py"] if step.kind in {"implement", "repair"} else [],
            evidence=[step.stepId],
        )

    async def verify_step(step: StepSpec, upstream_artifacts):
        nonlocal verifier_calls
        verifier_calls += 1
        if verifier_calls == 1:
            repair_step = _step(
                "repair_verify_fix_1",
                kind="repair",
                goal="repair based on verifier findings",
                depends_on=["implement_fix"],
                verification_mode="independent",
            )
            return VerificationReport(
                verdict="FAIL",
                summary="tests failed",
                checkedItems=["pytest"],
                failedItems=["pytest"],
                evidence=[VerificationEvidenceItem(name="pytest", result="FAIL", detail="1 failed")],
                remediationSteps=[repair_step],
                confidence=0.8,
                requiresUserInput=False,
            )
        return VerificationReport(
            verdict="PASS",
            summary="verified",
            checkedItems=["pytest"],
            failedItems=[],
            evidence=[VerificationEvidenceItem(name="pytest", result="PASS", detail="all passed")],
            remediationSteps=[],
            confidence=0.95,
            requiresUserInput=False,
        )

    runtime = OrchestrationRuntime(
        store=store,
        plan_builder=plan_builder,
        step_executor=execute_step,
        verification_executor=verify_step,
    )

    result = asyncio.run(runtime.execute("session-1", "fix the bug", "bugfix"))
    steps = store.list_steps_by_session("session-1")

    assert result == "answer"
    assert verifier_calls == 2
    assert any(step.kind == "repair" and step.status == "completed" for step in steps)


def test_resume_incomplete_runs_recovers_running_steps(tmp_path: Path):
    store = OrchestrationStore(tmp_path / "resume.db")
    plan = TaskGraphPlan(
        taskKind="implementation",
        steps=[
            _step("implement_fix", kind="implement", goal="fix issue"),
            _step("verify_fix", kind="verify", goal="verify issue", depends_on=["implement_fix"], verification_mode="independent"),
            _step("repair_fix", kind="repair", goal="repair issue", depends_on=["verify_fix"], verification_mode="independent"),
        ],
    )

    task_run = store.create_task_run(
        session_id="session-1",
        user_request="fix issue",
        task_kind="implementation",
        plan=plan,
    )
    steps = store.list_steps(task_run.taskRunId)
    implement_step, verify_step, repair_step = steps

    store.transition_step(implement_step.stepRunId, from_status="ready", to_status="running", summary="mid-flight")
    store.transition_step(verify_step.stepRunId, from_status="waiting_dependency", to_status="verifying", summary="verifying")
    store.transition_step(repair_step.stepRunId, from_status="waiting_dependency", to_status="repairing", summary="repairing")

    recovered = store.resume_incomplete_runs()
    refreshed = {step.stepId: step for step in store.list_steps(task_run.taskRunId)}

    assert task_run.taskRunId in recovered
    assert refreshed["implement_fix"].status == "ready"
    assert refreshed["verify_fix"].status == "ready"
    assert refreshed["repair_fix"].status == "ready"


def test_runtime_converts_ready_ask_user_step_into_waiting_user(tmp_path: Path):
    store = OrchestrationStore(tmp_path / "ask-user.db")
    plan = TaskGraphPlan(
        taskKind="question",
        steps=[
            _step("clarify_request", kind="ask_user", goal="Please clarify your request"),
        ],
    )

    async def plan_builder(task_kind: str, user_request: str) -> TaskGraphPlan:
        assert task_kind == "question"
        assert user_request == "??"
        return plan

    async def execute_step(step: StepSpec, upstream_artifacts):
        raise AssertionError("ask_user should not go through step executor")

    async def verify_step(step: StepSpec, upstream_artifacts):
        raise AssertionError("ask_user should not go through verifier")

    runtime = OrchestrationRuntime(
        store=store,
        plan_builder=plan_builder,
        step_executor=execute_step,
        verification_executor=verify_step,
    )

    result = asyncio.run(runtime.execute("session-1", "??", "question"))
    steps = store.list_steps_by_session("session-1")

    assert result == "Please clarify your request"
    assert steps[0].status == "waiting_user"


def test_runtime_fails_stalled_dependency_graph_without_raising(tmp_path: Path):
    store = OrchestrationStore(tmp_path / "stalled.db")
    plan = TaskGraphPlan(
        taskKind="implementation",
        steps=[
            _step("implement_fix", kind="implement", goal="fix issue", depends_on=["missing_step"]),
        ],
    )

    async def plan_builder(task_kind: str, user_request: str) -> TaskGraphPlan:
        return plan

    async def execute_step(step: StepSpec, upstream_artifacts):
        raise AssertionError("stalled graph should not execute steps")

    async def verify_step(step: StepSpec, upstream_artifacts):
        raise AssertionError("stalled graph should not verify steps")

    runtime = OrchestrationRuntime(
        store=store,
        plan_builder=plan_builder,
        step_executor=execute_step,
        verification_executor=verify_step,
    )

    result = asyncio.run(runtime.execute("session-1", "fix issue", "implementation"))
    steps = store.list_steps_by_session("session-1")

    assert "blocked" in result.lower()
    assert "missing_step" in result
    assert steps[0].status == "failed"
    assert steps[0].failureClass == "dependency"
