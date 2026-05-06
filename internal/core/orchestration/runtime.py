from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable

from internal.core.orchestration.store import OrchestrationStore
from internal.core.orchestration.types import (
    CheckpointPayload,
    StepExecutionResult,
    StepRun,
    StepSpec,
    TaskGraphPlan,
    TaskKind,
    VerificationReport,
)


PlanBuilder = Callable[[TaskKind, str], Awaitable[TaskGraphPlan]]
StepExecutor = Callable[[StepSpec, list[dict]], Awaitable[StepExecutionResult]]
VerificationExecutor = Callable[[StepSpec, list[dict]], Awaitable[VerificationReport]]


class OrchestrationRuntime:
    def __init__(
        self,
        *,
        store: OrchestrationStore,
        plan_builder: PlanBuilder,
        step_executor: StepExecutor,
        verification_executor: VerificationExecutor,
    ) -> None:
        self.store = store
        self.plan_builder = plan_builder
        self.step_executor = step_executor
        self.verification_executor = verification_executor
        self._lease_owner = f"runtime:{uuid.uuid4()}"

    async def execute(
        self,
        session_id: str,
        user_request: str,
        task_kind: TaskKind,
        on_todo_update: Callable[[str], None] | None = None,
    ) -> str:
        plan = await self.plan_builder(task_kind, user_request)
        task_run = self.store.create_task_run(
            session_id=session_id,
            user_request=user_request,
            task_kind=task_kind,
            plan=plan,
        )
        # Do not call resume_incomplete_runs() here — it mass-resets every
        # running/verifying/repairing row across all sessions/processes and
        # would clobber concurrent runtimes' active steps. Recovery should
        # happen at process startup via MainAgent.resume_incomplete_runs(),
        # not on every per-task execute.

        while True:
            self.store.refresh_waiting_dependencies(task_run.taskRunId)
            steps = self.store.list_steps(task_run.taskRunId)
            if on_todo_update:
                on_todo_update(self._render_status(steps))

            if steps and all(step.status == "completed" for step in steps):
                self.store.update_task_run_status(task_run.taskRunId, "completed")
                return self._final_result(task_run.taskRunId)

            discover_steps = self._runnable_steps(steps, {"discover", "plan"})
            if discover_steps:
                # return_exceptions=True so a single failing discover step
                # doesn't cancel siblings (which would leak their leases and
                # leave them stuck in `running`).
                results = await asyncio.gather(
                    *(self._execute_regular_step(step) for step in discover_steps),
                    return_exceptions=True,
                )
                for step, outcome in zip(discover_steps, results):
                    if isinstance(outcome, BaseException):
                        # Exception was already handled inside _execute_regular_step
                        # (lease released, step transitioned to failed).
                        pass
                continue

            verify_steps = self._runnable_steps(steps, {"verify"})
            if verify_steps:
                await self._execute_verification_step(verify_steps[0])
                continue

            writer_steps = self._runnable_steps(steps, {"implement", "repair"})
            if writer_steps:
                await self._execute_regular_step(writer_steps[0])
                continue

            synthesize_steps = self._runnable_steps(steps, {"synthesize"})
            if synthesize_steps:
                await self._execute_regular_step(synthesize_steps[0])
                continue

            ask_user_steps = self._runnable_steps(steps, {"ask_user"})
            if ask_user_steps:
                step = ask_user_steps[0]
                self.store.transition_step(
                    step.stepRunId,
                    from_status=step.status,
                    to_status="waiting_user",
                    summary=step.summary or step.goal,
                    failure_class="user_decision",
                )
                continue

            waiting_user = [step for step in steps if step.status == "waiting_user"]
            if waiting_user:
                self.store.update_task_run_status(task_run.taskRunId, "waiting_user")
                return waiting_user[0].summary or waiting_user[0].goal

            failed = [step for step in steps if step.status == "failed"]
            if failed:
                self.store.update_task_run_status(task_run.taskRunId, "failed")
                return failed[0].summary or failed[0].goal

            return self._handle_stalled_task(task_run.taskRunId, steps)

    def _runnable_steps(self, steps: list[StepRun], kinds: set[str]) -> list[StepRun]:
        return [step for step in steps if step.kind in kinds and step.status == "ready"]

    async def _execute_regular_step(self, step_run: StepRun) -> None:
        if not self.store.lease_step(step_run.stepRunId, lease_owner=self._lease_owner):
            return
        enter_status = "repairing" if step_run.kind == "repair" else "running"
        self.store.transition_step(
            step_run.stepRunId,
            from_status=step_run.status,
            to_status=enter_status,
            summary=f"Executing {step_run.stepId}",
        )
        try:
            try:
                result = await self.step_executor(
                    self._to_step_spec(step_run),
                    self._collect_upstream_artifacts(step_run),
                )
            except Exception as exc:
                # Avoid leaving the step stuck in `running`/`repairing`.
                current = self.store.get_step_run(step_run.stepRunId) or step_run
                self.store.transition_step(
                    step_run.stepRunId,
                    from_status=current.status,
                    to_status="failed",
                    summary=f"Step executor raised: {exc}",
                    failure_class="deterministic",
                )
                return
            await self._record_regular_result(step_run.stepRunId, result)
        finally:
            self.store.release_step_lease(step_run.stepRunId, lease_owner=self._lease_owner)

    async def _execute_verification_step(self, step_run: StepRun) -> None:
        if not self.store.lease_step(step_run.stepRunId, lease_owner=self._lease_owner):
            return
        self.store.transition_step(
            step_run.stepRunId,
            from_status=step_run.status,
            to_status="verifying",
            summary=f"Verifying {step_run.stepId}",
        )
        try:
            try:
                report = await self.verification_executor(
                    self._to_step_spec(step_run),
                    self._collect_upstream_artifacts(step_run),
                )
            except Exception as exc:
                current = self.store.get_step_run(step_run.stepRunId) or step_run
                self.store.transition_step(
                    step_run.stepRunId,
                    from_status=current.status,
                    to_status="failed",
                    summary=f"Verifier raised: {exc}",
                    failure_class="deterministic",
                )
                return
            await self._record_verification_result(step_run.stepRunId, report)
        finally:
            self.store.release_step_lease(step_run.stepRunId, lease_owner=self._lease_owner)

    async def _record_regular_result(self, step_run_id: str, result: StepExecutionResult) -> None:
        step = self.store.get_step_run(step_run_id)
        if step is None:
            raise KeyError(step_run_id)
        artifact = self.store.append_step_artifact(
            step_run_id,
            artifact_type="step_result",
            payload={
                "summary": result.summary,
                "result": result.result,
                "filesChanged": result.filesChanged,
                "commandsExecuted": result.commandsExecuted,
                "evidence": result.evidence,
                "unresolvedIssues": result.unresolvedIssues,
                "recoverySummary": result.recoverySummary,
            },
            summary=result.summary or step.goal,
            created_by="worker",
        )
        checkpoint = self.store.commit_checkpoint(
            step_run_id,
            CheckpointPayload(
                recoveryPoint=step.recoveryPoint,
                summary=result.summary or step.goal,
                artifactRefs=[artifact.artifactId],
                data=artifact.payload,
            ),
        )
        current = self.store.get_step_run(step_run_id)
        if current is None:
            raise KeyError(step_run_id)
        if result.status == "waiting_user" or result.requiresUserInput:
            self.store.transition_step(
                step_run_id,
                from_status=current.status,
                to_status="waiting_user",
                summary=result.summary or result.result or step.goal,
                failure_class="user_decision",
                last_checkpoint_id=checkpoint.checkpointId,
            )
            return
        if result.status == "failed":
            self.store.transition_step(
                step_run_id,
                from_status=current.status,
                to_status="failed",
                summary=result.summary or result.recoverySummary or step.goal,
                failure_class=result.failureClass or "deterministic",
                last_checkpoint_id=checkpoint.checkpointId,
            )
            return
        self.store.transition_step(
            step_run_id,
            from_status=current.status,
            to_status="completed",
            summary=result.summary or step.goal,
            last_checkpoint_id=checkpoint.checkpointId,
        )

    async def _record_verification_result(self, step_run_id: str, report: VerificationReport) -> None:
        step = self.store.get_step_run(step_run_id)
        if step is None:
            raise KeyError(step_run_id)
        artifact = self.store.append_step_artifact(
            step_run_id,
            artifact_type="verification_report",
            payload={
                "verdict": report.verdict,
                "summary": report.summary,
                "checkedItems": report.checkedItems,
                "failedItems": report.failedItems,
                "confidence": report.confidence,
                "requiresUserInput": report.requiresUserInput,
            },
            summary=report.summary or step.goal,
            created_by="verifier",
        )
        checkpoint = self.store.commit_checkpoint(
            step_run_id,
            CheckpointPayload(
                recoveryPoint=step.recoveryPoint,
                summary=report.summary or step.goal,
                artifactRefs=[artifact.artifactId],
                data=artifact.payload,
            ),
        )
        current = self.store.get_step_run(step_run_id)
        if current is None:
            raise KeyError(step_run_id)
        if report.verdict == "PASS":
            self.store.transition_step(
                step_run_id,
                from_status=current.status,
                to_status="completed",
                summary=report.summary or step.goal,
                last_checkpoint_id=checkpoint.checkpointId,
            )
            return
        if report.requiresUserInput or report.verdict == "BLOCKED":
            self.store.transition_step(
                step_run_id,
                from_status=current.status,
                to_status="waiting_user",
                summary=report.summary or step.goal,
                failure_class="user_decision",
                last_checkpoint_id=checkpoint.checkpointId,
            )
            return

        # Repair steps must NOT depend on the failed verify step (the very step we
        # are routing through them) — that would create a cycle once we point the
        # verify step's dependsOn at the repair_ids below. Repair steps inherit
        # only the verify step's UPSTREAM dependencies, so they can run as soon
        # as those upstream artifacts are available.
        remediation_steps = list(report.remediationSteps)
        if not remediation_steps:
            remediation_steps = [
                StepSpec(
                    stepId=f"repair_{step.stepId}_fallback",
                    kind="repair",
                    goal=report.summary or f"Repair {step.goal}",
                    dependsOn=list(dict.fromkeys(step.dependsOn)),
                    executor="worker",
                    inputs={"verificationSummary": report.summary, "failedItems": report.failedItems},
                    contract=step.contract,
                    verificationMode=step.verificationMode,
                    retryPolicy=step.retryPolicy,
                    recoveryPoint=f"{step.recoveryPoint}:repair",
                )
            ]

        repair_ids: list[str] = []
        for remediation in remediation_steps:
            # Inherit upstream deps but don't add a self-loop on the verify step.
            remediation.dependsOn = list(
                dict.fromkeys([
                    dep for dep in [*remediation.dependsOn, *step.dependsOn] if dep != step.stepId
                ])
            )
            inserted = self.store.insert_step(task_run_id=step.taskRunId, step_spec=remediation, status="ready")
            repair_ids.append(inserted.stepId)

        # Re-queue the verify step so it waits on the new repairs and can re-run
        # once they complete. This bypasses the strict transition validator
        # because waiting_dependency is not in _TRANSITIONS["verifying"]; we own
        # the row right now (the verify executor still holds the lease) so the
        # direct dependency rewrite is safe here.
        self.store.update_step_dependencies(
            step_run_id,
            list(dict.fromkeys([*step.dependsOn, *repair_ids])),
            status="waiting_dependency",
        )
        with self.store._connect() as conn:  # noqa: SLF001
            conn.execute(
                """
                UPDATE orchestration_step_runs
                SET summary = ?, last_checkpoint_id = ?, failure_class = ?, updated_at = ?
                WHERE step_run_id = ?
                """,
                (
                    report.summary or step.goal,
                    checkpoint.checkpointId,
                    "deterministic",
                    int(time.time() * 1000),
                    step_run_id,
                ),
            )
        self.store.add_recovery_event(
            task_run_id=step.taskRunId,
            step_run_id=step_run_id,
            event_type="verification_failed",
            detail=report.summary or "verification failed",
        )

    def _collect_upstream_artifacts(self, step_run: StepRun) -> list[dict]:
        steps = {step.stepId: step for step in self.store.list_steps(step_run.taskRunId)}
        artifacts: list[dict] = []
        for dep_id in step_run.dependsOn:
            dep = steps.get(dep_id)
            if dep is None:
                continue
            artifacts.extend([artifact.payload for artifact in self.store.list_step_artifacts(dep.stepRunId)])
        return artifacts

    def _to_step_spec(self, step_run: StepRun) -> StepSpec:
        return StepSpec(
            stepId=step_run.stepId,
            kind=step_run.kind,
            goal=step_run.goal,
            dependsOn=step_run.dependsOn,
            executor=step_run.executor,
            inputs=step_run.inputs,
            contract=step_run.contract,
            verificationMode=step_run.verificationMode,
            retryPolicy=step_run.retryPolicy,
            recoveryPoint=step_run.recoveryPoint,
        )

    def _final_result(self, task_run_id: str) -> str:
        steps = self.store.list_steps(task_run_id)
        for step in steps:
            if step.kind != "synthesize" or step.status != "completed":
                continue
            artifacts = self.store.list_step_artifacts(step.stepRunId)
            if not artifacts:
                continue
            payload = artifacts[-1].payload
            if payload.get("result"):
                return str(payload["result"])
            if artifacts[-1].summary:
                return artifacts[-1].summary
        # Fallback: only consider completed steps so a failed/repair payload
        # never gets returned as the user-facing final answer.
        for step in reversed(steps):
            if step.status != "completed":
                continue
            artifacts = self.store.list_step_artifacts(step.stepRunId)
            if not artifacts:
                continue
            payload = artifacts[-1].payload
            if payload.get("result"):
                return str(payload["result"])
            if artifacts[-1].summary:
                return artifacts[-1].summary
        return ""

    def _handle_stalled_task(self, task_run_id: str, steps: list[StepRun]) -> str:
        steps_by_id = {step.stepId: step for step in steps}
        # Include orphaned-running statuses so a step leaked by a crashed worker
        # is force-failed instead of vanishing silently.
        stalled_steps = [
            step for step in steps
            if step.status in {
                "waiting_dependency", "ready", "queued", "planning",
                "running", "verifying", "repairing",
            }
        ]
        if not stalled_steps:
            self.store.update_task_run_status(task_run_id, "failed")
            return "Task blocked because orchestration reached a non-terminal state with no runnable steps."

        summaries: list[str] = []
        for step in stalled_steps:
            detail = "task graph stalled"
            failure_class = "deterministic"
            if step.status == "waiting_dependency":
                missing_dependencies = [dep_id for dep_id in step.dependsOn if dep_id not in steps_by_id]
                blocked_dependencies = [
                    dep_id
                    for dep_id in step.dependsOn
                    if dep_id in steps_by_id and steps_by_id[dep_id].status != "completed"
                ]
                failure_class = "dependency"
                if missing_dependencies:
                    detail = f"blocked by missing dependencies: {', '.join(missing_dependencies)}"
                elif blocked_dependencies:
                    detail = f"blocked by unresolved dependencies: {', '.join(blocked_dependencies)}"
                else:
                    detail = "blocked by unresolved dependency state"
            elif step.kind == "ask_user":
                detail = step.summary or step.goal
                failure_class = "user_decision"
            elif step.status == "ready":
                detail = f"ready step {step.stepId} of kind {step.kind} has no execution path"

            self.store.add_recovery_event(
                task_run_id=task_run_id,
                step_run_id=step.stepRunId,
                event_type="task_stalled",
                detail=detail,
            )
            self.store.transition_step(
                step.stepRunId,
                from_status=step.status,
                to_status="failed",
                summary=detail,
                failure_class=failure_class,
            )
            summaries.append(f"{step.stepId}: {detail}")

        self.store.update_task_run_status(task_run_id, "failed")
        return "Task blocked because orchestration stalled.\n" + "\n".join(summaries)

    @staticmethod
    def _render_status(steps: list[StepRun]) -> str:
        lines = ["[TODO] phase=orchestration"]
        for step in steps:
            lines.append(f"- {step.stepId} [{step.status}] {step.goal}")
        return "\n".join(lines)
