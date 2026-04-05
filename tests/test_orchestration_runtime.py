import asyncio
from types import SimpleNamespace

from internal.agents.main_agent import MainAgent
from internal.core.protocol.task_notification import parse_task_notification_xml
from internal.core.tasks.completion_gate import decide_completion, needs_verification
from internal.core.tasks.task_types import VerificationResult, WorkerResult
from internal.services.subagent_tasks import AgentToolInput, BaseTask, SubagentTaskManager


def _bind_main_methods(fake_main: object) -> None:
    method_names = [
        "coordinator_handle_user_turn",
        "coordinator_handle_user_turn_stream",
    ]
    for method_name in method_names:
        method = getattr(MainAgent, method_name)
        setattr(fake_main, method_name, method.__get__(fake_main, type(fake_main)))


def test_completion_gate_requires_verification_for_implementation():
    worker = WorkerResult(
        taskId="t1",
        status="completed",
        summary="done",
        result="implemented",
        filesChanged=["a.py", "b.py", "c.py", "d.py"],
        commandsExecuted=["pytest -q"],
        evidence=["$ pytest -q"],
        unresolvedIssues=[],
    )

    decision = decide_completion(worker)
    assert decision.done is False
    assert decision.nextAction == "run-verification"
    assert needs_verification(
        {
            "taskKind": "implementation",
            "filesChanged": worker.filesChanged,
            "commandsExecuted": worker.commandsExecuted,
        }
    ) is True


def test_completion_gate_passes_after_verification_pass():
    worker = WorkerResult(
        taskId="t2",
        status="completed",
        summary="done",
        result="implemented",
        filesChanged=["a.py", "b.py", "c.py"],
        commandsExecuted=["pytest -q"],
        evidence=["$ pytest -q"],
        unresolvedIssues=[],
    )
    verification = VerificationResult(
        taskId="t2",
        verdict="PASS",
        summary="verified",
        evidence=[],
        missingRequirements=[],
        suspectedProblems=[],
    )

    decision = decide_completion(worker, verification)
    assert decision.done is True
    assert decision.nextAction == "finalize"


def test_task_notification_roundtrip_from_manager():
    notifications: list[str] = []

    async def fake_worker(task: BaseTask, prompt: str) -> str:
        if task.subagentType == "verification":
            return "VERDICT: PASS\n$ pytest -q\nall passed"
        return "Implemented feature\nTouched a.py b.py c.py\n$ pytest -q"

    manager = SubagentTaskManager(fake_worker, notifications.append)

    result = asyncio.run(
        manager.spawnAgentTask(
            AgentToolInput(
                prompt="implement the feature",
                subagent_type="implementation",
                run_in_background=False,
            ),
            session_id="s1",
        )
    )

    assert result["status"] == "completed"
    assert notifications
    parsed = parse_task_notification_xml(notifications[-1])
    assert parsed.status == "completed"
    assert parsed.taskId


def test_verification_fail_must_retry_worker_before_complete():
    notifications: list[str] = []
    calls = {"worker": 0, "verifier": 0}

    async def fake_worker(task: BaseTask, prompt: str) -> str:
        if task.subagentType == "verification":
            calls["verifier"] += 1
            if calls["verifier"] == 1:
                return "VERDICT: FAIL\n$ pytest -q\n1 failed"
            return "VERDICT: PASS\n$ pytest -q\nall passed"
        calls["worker"] += 1
        if calls["worker"] == 1:
            return "First implementation attempt\nEdited a.py b.py c.py\n$ pytest -q"
        return "Second implementation attempt\nEdited a.py b.py c.py\n$ pytest -q"

    manager = SubagentTaskManager(fake_worker, notifications.append)

    result = asyncio.run(
        manager.spawnAgentTask(
            AgentToolInput(
                prompt="fix API bug",
                subagent_type="implementation",
                run_in_background=False,
            ),
            session_id="s1",
        )
    )

    assert result["status"] == "completed"
    assert calls["worker"] >= 2
    assert calls["verifier"] >= 2


def test_retry_loop_has_max_attempts_and_fails():
    notifications: list[str] = []
    calls = {"worker": 0, "verifier": 0}

    async def fake_worker(task: BaseTask, prompt: str) -> str:
        if task.subagentType == "verification":
            calls["verifier"] += 1
            return "VERDICT: FAIL\n$ pytest -q\nstill failing"
        calls["worker"] += 1
        return "Attempt implementation\nEdited a.py b.py c.py\n$ pytest -q"

    manager = SubagentTaskManager(fake_worker, notifications.append)

    result = asyncio.run(
        manager.spawnAgentTask(
            AgentToolInput(
                prompt="fix API bug",
                subagent_type="implementation",
                run_in_background=False,
            ),
            session_id="s1",
        )
    )

    assert result["status"] == "failed"
    assert calls["worker"] == 4
    assert calls["verifier"] == 4


def test_coordinator_handle_user_turn_uses_execute_turn_core():
    async def scenario() -> None:
        main_agent = SimpleNamespace()
        _bind_main_methods(main_agent)

        async def fake_execute_turn_core(
            prompt: str,
            message_history=None,
            skip_plan_execution=True,
        ):
            _ = message_history
            _ = skip_plan_execution
            return f"handled:{prompt}"

        main_agent._execute_turn_core = fake_execute_turn_core

        text = await main_agent.coordinator_handle_user_turn(
            "please handle this in the background"
        )
        assert text == "handled:please handle this in the background"

    asyncio.run(scenario())


def test_coordinator_stream_has_no_progress_labels():
    async def scenario() -> None:
        main_agent = SimpleNamespace()
        _bind_main_methods(main_agent)

        async def fake_handle_user_turn(
            _prompt,
            message_history=None,
            on_todo_update=None,
        ):
            _ = message_history
            _ = on_todo_update
            return "final output"

        main_agent.coordinator_handle_user_turn = fake_handle_user_turn  # type: ignore[method-assign]

        chunks: list[str] = []
        async for chunk in main_agent.coordinator_handle_user_turn_stream(
            "please handle it",
            message_history=None,
        ):
            chunks.append(chunk)

        text = "".join(chunks)
        assert "[TODO]" not in text
        assert "final output" in text

    asyncio.run(scenario())
