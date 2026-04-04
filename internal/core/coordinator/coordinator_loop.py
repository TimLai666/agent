from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from internal.core.agents.agent_types import SpawnVerificationInput, SpawnWorkerInput
from internal.core.tasks.task_types import CoordinatorTodo, TaskKind, TodoStatus, VerificationResult, WorkerResult


MAX_COORDINATOR_LOOP = 40
MAX_TODO_RETRY = 3
MAX_STUCK_TURNS = 6


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
        if dep is None:
            return False
        if dep.status != "completed":
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
        "流程已進入 blocked 狀態。",
        f"原因：{reason}",
        "",
        "已完成項目：",
    ]
    if completed:
        lines.extend(f"- {t.id}: {t.title}" for t in completed)
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("未完成或異常項目：")
    if unresolved:
        for todo in unresolved:
            detail = todo.blockingReason or todo.notes or "狀態未完成"
            lines.append(f"- {todo.id}: {todo.title} [{todo.status}] {detail}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def _build_aggregate_worker_result(todos: list[CoordinatorTodo]) -> WorkerResult:
    completed = [todo for todo in todos if todo.status == "completed"]
    summary = completed[-1].title if completed else "已完成執行"
    result_lines: list[str] = []
    files_changed: list[str] = []
    commands: list[str] = []
    evidence: list[str] = []
    unresolved: list[str] = []

    for todo in completed:
        if todo.result.strip():
            result_lines.append(f"[{todo.id}] {todo.result.strip()}")
        _merge_unique(files_changed, [item for item in todo.evidence if "." in item and "/" in item])
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


@dataclass
class CoordinatorTurnContext:
    userRequest: str
    taskKind: TaskKind = "research"


@dataclass
class CoordinatorPlan:
    type: str
    finalAnswer: str = ""
    workerSpec: SpawnWorkerInput | None = None


async def run_coordinator_turn(
    ctx: CoordinatorTurnContext,
    *,
    make_or_update_plan: Callable[[CoordinatorTurnContext], Awaitable[CoordinatorPlan]],
    spawn_worker: Callable[[SpawnWorkerInput], Awaitable[WorkerResult]],
    spawn_verification_worker: Callable[[SpawnVerificationInput], Awaitable[VerificationResult]],
    synthesize_final_answer: Callable[[CoordinatorTurnContext, WorkerResult, VerificationResult | None], str],
    augment_context_with_failure: Callable[[CoordinatorTurnContext, WorkerResult, VerificationResult | None], CoordinatorTurnContext],
) -> str:
    todos: list[CoordinatorTodo] = []
    todo_plans: dict[str, CoordinatorPlan] = {}
    loop_count = 0
    stuck_turns = 0

    while True:
        loop_count += 1
        if loop_count > MAX_COORDINATOR_LOOP:
            return _build_stuck_report(todos, "Exceeded max loop count")

        progress_made = False

        if not todos:
            plan = await make_or_update_plan(ctx)
            todo = CoordinatorTodo(
                id=_make_todo_id(todos),
                title="初始執行任務",
                description=ctx.userRequest,
                status="pending",
                priority="high",
                assignedTo="main_agent",
            )
            if plan.type == "answer-directly":
                todo.title = "直接回覆任務"
                todo.notes = plan.finalAnswer
            elif plan.type == "spawn-worker" and plan.workerSpec is not None:
                todo.title = plan.workerSpec.title or "worker-task"
                todo.assignedTo = plan.workerSpec.agentType
                todo.description = plan.workerSpec.instruction
            else:
                return "無法產生可執行計畫。"

            todos.append(todo)
            todo_plans[todo.id] = plan
            progress_made = True

        next_todo = _select_next_runnable_todo(todos)
        if next_todo is not None:
            next_todo.status = "in_progress"
            progress_made = True
            plan = todo_plans.get(next_todo.id)

            if plan is None:
                next_todo.status = "failed"
                next_todo.blockingReason = "缺少對應執行計畫"
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
                    next_todo.notes = "; ".join(worker_result.unresolvedIssues) or worker_result.summary or "worker execution failed"
                    if next_todo.retryCount <= MAX_TODO_RETRY:
                        next_todo.status = "retrying"
                        ctx = augment_context_with_failure(ctx, worker_result, None)
                    else:
                        next_todo.status = "failed"
                        next_todo.blockingReason = next_todo.notes or "exceeded max retry"
            else:
                next_todo.status = "impossible"
                next_todo.blockingReason = "todo 對應計畫無效"

            if next_todo.status in {"completed", "failed", "impossible"}:
                progress_made = True
            if next_todo.status in {"blocked", "failed", "impossible"} and not next_todo.blockingReason.strip():
                next_todo.blockingReason = next_todo.notes or "未提供阻塞原因"

            if progress_made:
                stuck_turns = 0
            else:
                stuck_turns += 1
            continue

        if not _can_enter_validation(todos):
            return _build_stuck_report(todos, "Todos unresolved but no runnable task found")

        aggregate_worker = _build_aggregate_worker_result(todos)
        completed_todo_ids = {todo.id for todo in todos if todo.status == "completed"}
        has_executed_worker_todo = any(
            todo_id in completed_todo_ids and plan.type == "spawn-worker"
            for todo_id, plan in todo_plans.items()
        )
        if not has_executed_worker_todo:
            return synthesize_final_answer(ctx, aggregate_worker, None)

        verification = await spawn_verification_worker(
            SpawnVerificationInput(
                originalUserRequest=ctx.userRequest,
                workerResult=aggregate_worker,
                filesChanged=aggregate_worker.filesChanged,
            )
        )

        if verification.verdict == "PASS":
            unexplained = [
                todo
                for todo in todos
                if todo.status in {"blocked", "failed", "impossible"} and not todo.blockingReason.strip()
            ]
            if unexplained:
                return _build_stuck_report(todos, "Found unresolved blocked/failed/impossible todos without reason")
            return synthesize_final_answer(ctx, aggregate_worker, verification)

        remediation_todos = verification.remediationTodos
        if not remediation_todos:
            return _build_stuck_report(todos, "Validation failed without remediation path")

        for remediation in remediation_todos:
            remediation.id = _make_todo_id(todos)
            remediation.status = "pending"
            remediation.assignedTo = remediation.assignedTo or "main_agent"
            todos.append(remediation)

            remediation_ctx = CoordinatorTurnContext(
                userRequest=f"{ctx.userRequest}\n\n[Validation remediation]\n{remediation.title}\n{remediation.description}",
                taskKind="implementation",
            )
            remediation_plan = await make_or_update_plan(remediation_ctx)
            if remediation_plan.type == "answer-directly":
                remediation.notes = remediation_plan.finalAnswer
            elif remediation_plan.type == "spawn-worker" and remediation_plan.workerSpec is not None:
                remediation.assignedTo = remediation_plan.workerSpec.agentType
            else:
                remediation.status = "impossible"
                remediation.blockingReason = "Planner 無法為 remediation 產生執行計畫"
            todo_plans[remediation.id] = remediation_plan

        progress_made = True
        if progress_made:
            stuck_turns = 0
        else:
            stuck_turns += 1

        if stuck_turns >= MAX_STUCK_TURNS:
            return _build_stuck_report(todos, "No effective progress detected for multiple turns")
