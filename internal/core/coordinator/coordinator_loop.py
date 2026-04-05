from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from internal.core.agents.agent_types import SpawnVerificationInput, SpawnWorkerInput
from internal.core.tasks.task_types import (
    CoordinatorTodo,
    TaskKind,
    TodoStatus,
    VerificationResult,
    WorkerResult,
)


MAX_COORDINATOR_LOOP = 40
MAX_TODO_RETRY = 3
MAX_STUCK_TURNS = 6
MAX_VALIDATION_FAILURE_RETRIES = 1
TASK_KINDS_REQUIRING_VERIFICATION = {"implementation", "bugfix", "infra"}


def _requires_blocking_reason(status: TodoStatus) -> bool:
    return status in {"blocked", "failed", "impossible"}


def _can_enter_validation(todos: list[CoordinatorTodo]) -> bool:
    for todo in todos:
        if todo.status in {"pending", "in_progress", "retrying"}:
            return False
        if _requires_blocking_reason(todo.status) and not todo.blockingReason.strip():
            return False
    return True


def _is_dependency_satisfied(todo: CoordinatorTodo, index: dict[str, CoordinatorTodo]) -> bool:
    for dep_id in todo.dependencies:
        dep = index.get(dep_id)
        if dep is None or dep.status != "completed":
            return False
    return True


def _select_next_runnable_todo(todos: list[CoordinatorTodo]) -> CoordinatorTodo | None:
    index = {todo.id: todo for todo in todos}
    for todo in todos:
        if todo.status not in {"pending", "retrying"}:
            continue
        if todo.retryCount > MAX_TODO_RETRY:
            continue
        if not _is_dependency_satisfied(todo, index):
            continue
        return todo
    return None


def _make_todo_id(existing: list[CoordinatorTodo]) -> str:
    return f"todo_{len(existing) + 1:03d}"


def _merge_unique(target: list[str], source: list[str]) -> list[str]:
    seen = set(target)
    for item in source:
        if item not in seen:
            target.append(item)
            seen.add(item)
    return target


def _build_stuck_report(todos: list[CoordinatorTodo], reason: str) -> str:
    completed = [t for t in todos if t.status == "completed"]
    unresolved = [t for t in todos if t.status != "completed"]
    lines = [
        "Coordinator got stuck before finishing the request.",
        f"Reason: {reason}",
        "",
        "Completed todos:",
    ]
    if completed:
        lines.extend(f"- {t.id}: {t.title}" for t in completed)
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("Remaining todos:")
    if unresolved:
        for todo in unresolved:
            detail = todo.blockingReason or todo.notes or "no additional detail"
            lines.append(f"- {todo.id}: {todo.title} [{todo.status}] {detail}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def _build_aggregate_worker_result(todos: list[CoordinatorTodo]) -> WorkerResult:
    completed = [todo for todo in todos if todo.status == "completed"]
    summary = completed[-1].title if completed else "coordinator-run"
    result_lines: list[str] = []
    files_changed: list[str] = []
    commands: list[str] = []
    evidence: list[str] = []
    unresolved: list[str] = []

    for todo in completed:
        if todo.result.strip():
            result_lines.append(f"[{todo.id}] {todo.result.strip()}")
        _merge_unique(evidence, todo.evidence)

    for todo in todos:
        if todo.status in {"blocked", "failed", "impossible"}:
            unresolved.append(f"{todo.id}: {todo.blockingReason or todo.notes or todo.title}")

    return WorkerResult(
        taskId="coordinator-run",
        status="completed",
        summary=summary,
        result="\n".join(result_lines).strip() or summary,
        filesChanged=files_changed,
        commandsExecuted=commands,
        evidence=evidence,
        unresolvedIssues=unresolved,
    )


def _todo_signature(todo: CoordinatorTodo) -> tuple[str, str]:
    return (todo.title.strip().lower(), todo.description.strip().lower())


def _format_todo_snapshot(phase: str, todos: list[CoordinatorTodo]) -> str:
    lines = [f"[TODO] phase={phase}"]
    if not todos:
        lines.append("- (empty)")
        return "\n".join(lines)

    for todo in todos:
        desc = todo.title.strip() or todo.description.strip() or todo.id
        suffix = ""
        if todo.status in {"blocked", "failed", "impossible"}:
            suffix = f" | reason={todo.blockingReason or todo.notes or 'n/a'}"
        lines.append(f"- {todo.id} [{todo.status}] {desc}{suffix}")
    return "\n".join(lines)


def _emit_todo_snapshot(
    phase: str,
    todos: list[CoordinatorTodo],
    callback: Callable[[str], None] | None,
) -> None:
    if callback is None:
        return
    callback(_format_todo_snapshot(phase, todos))


@dataclass
class CoordinatorTurnContext:
    userRequest: str
    taskKind: TaskKind = "research"


@dataclass
class CoordinatorPlan:
    type: str
    finalAnswer: str = ""
    workerSpec: SpawnWorkerInput | None = None
    workerSpecs: list[SpawnWorkerInput] = field(default_factory=list)


async def run_coordinator_turn(
    ctx: CoordinatorTurnContext,
    *,
    make_or_update_plan: Callable[[CoordinatorTurnContext], Awaitable[CoordinatorPlan]],
    spawn_worker: Callable[[SpawnWorkerInput], Awaitable[WorkerResult]],
    spawn_verification_worker: Callable[[SpawnVerificationInput], Awaitable[VerificationResult]],
    synthesize_final_answer: Callable[[CoordinatorTurnContext, WorkerResult, VerificationResult | None], str],
    augment_context_with_failure: Callable[[CoordinatorTurnContext, WorkerResult, VerificationResult | None], CoordinatorTurnContext],
    on_todo_update: Callable[[str], None] | None = None,
) -> str:
    todos: list[CoordinatorTodo] = []
    todo_plans: dict[str, CoordinatorPlan] = {}
    loop_count = 0
    stuck_turns = 0
    validation_failures = 0

    while True:
        loop_count += 1
        if loop_count > MAX_COORDINATOR_LOOP:
            return _build_stuck_report(todos, "exceeded max loop count")

        progress_made = False

        if not todos:
            plan = await make_or_update_plan(ctx)
            if plan.type == "answer-directly":
                return plan.finalAnswer
            if plan.type != "spawn-worker":
                return "Coordinator could not produce a runnable plan."

            specs = list(plan.workerSpecs)
            if not specs and plan.workerSpec is not None:
                specs = [plan.workerSpec]
            if not specs:
                return "Coordinator did not receive any worker steps."

            prev_todo_id: str | None = None
            for index, spec in enumerate(specs, start=1):
                todo = CoordinatorTodo(
                    id=_make_todo_id(todos),
                    title=spec.title or f"worker-task-{index}",
                    description=spec.instruction,
                    status="pending",
                    priority="high",
                    assignedTo=spec.agentType,
                    dependencies=[prev_todo_id] if prev_todo_id else [],
                )
                todos.append(todo)
                todo_plans[todo.id] = CoordinatorPlan(type="spawn-worker", workerSpec=spec)
                prev_todo_id = todo.id

            if len(specs) > 1:
                _emit_todo_snapshot("planning", todos, on_todo_update)
            progress_made = True

        next_todo = _select_next_runnable_todo(todos)
        if next_todo is not None:
            next_todo.status = "in_progress"
            _emit_todo_snapshot("executing", todos, on_todo_update)
            progress_made = True
            plan = todo_plans.get(next_todo.id)

            if plan is None:
                next_todo.status = "failed"
                next_todo.blockingReason = "missing worker plan for todo"
            elif plan.type == "answer-directly":
                next_todo.result = plan.finalAnswer
                next_todo.status = "completed"
            elif plan.type == "spawn-worker" and plan.workerSpec is not None:
                worker_result = await spawn_worker(plan.workerSpec)
                next_todo.result = worker_result.result
                _merge_unique(next_todo.evidence, worker_result.evidence)

                if worker_result.status == "completed" and not worker_result.unresolvedIssues:
                    next_todo.status = "completed"
                else:
                    next_todo.retryCount += 1
                    next_todo.notes = (
                        "; ".join(worker_result.unresolvedIssues)
                        or worker_result.summary
                        or "worker execution failed"
                    )
                    if next_todo.retryCount <= MAX_TODO_RETRY:
                        next_todo.status = "retrying"
                        ctx = augment_context_with_failure(ctx, worker_result, None)
                    else:
                        next_todo.status = "failed"
                        next_todo.blockingReason = next_todo.notes or "exceeded max retry"
            else:
                next_todo.status = "impossible"
                next_todo.blockingReason = "todo has an invalid plan"

            if next_todo.status in {"blocked", "failed", "impossible"} and not next_todo.blockingReason.strip():
                next_todo.blockingReason = next_todo.notes or "missing failure reason"

            _emit_todo_snapshot("executing", todos, on_todo_update)
            stuck_turns = 0 if progress_made else stuck_turns + 1
            continue

        if not _can_enter_validation(todos):
            _emit_todo_snapshot("blocked", todos, on_todo_update)
            return _build_stuck_report(todos, "todos unresolved but no runnable task found")

        aggregate_worker = _build_aggregate_worker_result(todos)
        completed_todo_ids = {todo.id for todo in todos if todo.status == "completed"}
        has_executed_worker_todo = any(
            todo_id in completed_todo_ids and plan.type == "spawn-worker"
            for todo_id, plan in todo_plans.items()
        )

        if not has_executed_worker_todo or ctx.taskKind not in TASK_KINDS_REQUIRING_VERIFICATION:
            _emit_todo_snapshot("completed", todos, on_todo_update)
            return synthesize_final_answer(ctx, aggregate_worker, None)

        _emit_todo_snapshot("validating", todos, on_todo_update)
        verification = await spawn_verification_worker(
            SpawnVerificationInput(
                originalUserRequest=ctx.userRequest,
                workerResult=aggregate_worker,
                filesChanged=aggregate_worker.filesChanged,
            )
        )

        if verification.verdict == "PASS":
            _emit_todo_snapshot("completed", todos, on_todo_update)
            return synthesize_final_answer(ctx, aggregate_worker, verification)

        validation_failures += 1
        remediation_todos = verification.remediationTodos
        if validation_failures > MAX_VALIDATION_FAILURE_RETRIES or not remediation_todos:
            _emit_todo_snapshot("finalizing", todos, on_todo_update)
            return synthesize_final_answer(ctx, aggregate_worker, verification)

        existing_signatures = {_todo_signature(todo) for todo in todos}
        added_any = False

        for remediation in remediation_todos:
            signature = _todo_signature(remediation)
            if signature in existing_signatures:
                continue

            remediation.id = _make_todo_id(todos)
            remediation.status = "pending"
            remediation.assignedTo = remediation.assignedTo or "main_agent"
            todos.append(remediation)
            existing_signatures.add(signature)
            added_any = True

            remediation_ctx = CoordinatorTurnContext(
                userRequest=(
                    f"{ctx.userRequest}\n\n"
                    f"[Validation remediation]\n{remediation.title}\n{remediation.description}"
                ),
                taskKind="implementation",
            )
            remediation_plan = await make_or_update_plan(remediation_ctx)
            if remediation_plan.type == "answer-directly":
                remediation.result = remediation_plan.finalAnswer
                remediation.status = "completed"
            elif remediation_plan.type == "spawn-worker" and remediation_plan.workerSpec is not None:
                remediation.assignedTo = remediation_plan.workerSpec.agentType
            else:
                remediation.status = "impossible"
                remediation.blockingReason = "coordinator could not create a remediation step"
            todo_plans[remediation.id] = remediation_plan

        if not added_any:
            _emit_todo_snapshot("finalizing", todos, on_todo_update)
            return synthesize_final_answer(ctx, aggregate_worker, verification)

        _emit_todo_snapshot("executing", todos, on_todo_update)
        stuck_turns = 0 if progress_made or added_any else stuck_turns + 1

        if stuck_turns >= MAX_STUCK_TURNS:
            _emit_todo_snapshot("blocked", todos, on_todo_update)
            return _build_stuck_report(todos, "no effective progress detected for multiple turns")
