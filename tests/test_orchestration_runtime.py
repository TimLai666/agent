import asyncio
from types import SimpleNamespace

from internal.agents.main_agent import MainAgent
from internal.core.agents.agent_types import SpawnWorkerInput
from internal.core.protocol.task_notification import parse_task_notification_xml
from internal.core.tasks.completion_gate import decide_completion, needs_verification
from internal.core.tasks.task_types import VerificationResult, WorkerResult
from internal.services.subagent_tasks import AgentToolInput, BaseTask, SubagentTaskManager


def _bind_main_coordinator_methods(fake_main: object) -> None:
    method_names = [
        "_build_planning_instruction",
        "coordinator_handle_user_turn",
        "coordinator_handle_user_turn_stream",
        "_coordinator_make_or_update_plan",
        "_coordinator_generate_main_guidance",
        "_coordinator_spawn_worker",
        "_coordinator_spawn_verification",
        "_coordinator_find_task_notification",
        "_coordinator_augment_context_with_failure",
        "_coordinator_infer_task_kind",
        "_coordinator_looks_like_direct_question",
        "_coordinator_should_run_background",
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
                prompt="請實作新功能",
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
                prompt="修 API bug",
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
                prompt="修 API bug",
                subagent_type="implementation",
                run_in_background=False,
            ),
            session_id="s1",
        )
    )

    assert result["status"] == "failed"
    assert calls["worker"] == 4
    assert calls["verifier"] == 4


def test_spawn_worker_falls_back_to_task_state_when_notification_missing():
    async def fake_worker(task: BaseTask, prompt: str) -> str:
        if task.subagentType == "verification":
            return "VERDICT: PASS\n$ pytest -q\nall passed"
        return "Implemented change\nEdited a.py\n$ pytest -q"

    manager = SubagentTaskManager(fake_worker, lambda _xml: None)
    main_agent = SimpleNamespace(
        _task_manager=manager,
        _session_id="s1",
        _task_notifications=[],
    )
    _bind_main_coordinator_methods(main_agent)

    worker_result = asyncio.run(
        main_agent._coordinator_spawn_worker(
            SpawnWorkerInput(
                agentType="implementation",
                title="impl-task",
                instruction="請修正問題",
                runInBackground=False,
                originalUserRequest="請修正問題",
            )
        )
    )

    assert worker_result.status == "completed"
    assert worker_result.taskId


def test_coordinator_can_respond_immediately_with_background_worker():
    async def scenario() -> None:
        notifications: list[str] = []

        async def fake_worker(task: BaseTask, prompt: str) -> str:
            await asyncio.sleep(0.05)
            if task.subagentType == "verification":
                return "VERDICT: PASS\n$ pytest -q\nall passed"
            return "Background work completed\nEdited a.py\n$ pytest -q"

        manager = SubagentTaskManager(fake_worker, notifications.append)
        main_agent = SimpleNamespace(
            _task_manager=manager,
            _session_id="s1",
            _task_notifications=[],
            _execute_turn_core=None,
        )
        _bind_main_coordinator_methods(main_agent)

        text = await main_agent.coordinator_handle_user_turn("請協調派工，背景處理這件事，先回覆我")
        assert "task_id:" in text
        tasks = manager.listTasks("s1")
        assert tasks
        assert tasks[0]["status"] in {"pending", "running", "completed"}

        await asyncio.sleep(0.12)
        tasks_after = manager.listTasks("s1")
        assert tasks_after[0]["status"] == "completed"

    asyncio.run(scenario())


def test_coordinator_stream_has_no_progress_labels():
    async def scenario() -> None:
        main_agent = SimpleNamespace()
        _bind_main_coordinator_methods(main_agent)

        async def fake_handle_user_turn(_prompt, message_history=None, on_todo_update=None):
            return "final output"

        main_agent.coordinator_handle_user_turn = fake_handle_user_turn  # type: ignore[method-assign]

        chunks: list[str] = []
        async for chunk in main_agent.coordinator_handle_user_turn_stream(
            "請協調處理",
            message_history=None,
        ):
            chunks.append(chunk)

        text = "".join(chunks)
        assert "[進度]" not in text
        assert "final output" in text

    asyncio.run(scenario())


def test_planning_instruction_prioritizes_skills_and_tools():
    main_agent = SimpleNamespace()
    _bind_main_coordinator_methods(main_agent)
    instruction = main_agent._build_planning_instruction("請幫我完成任務")

    assert "優先使用現有 skills 與已可用 tools" in instruction
    assert "User request" in instruction


def test_coordinator_plan_uses_main_guidance_from_execute_turn():
    async def scenario() -> None:
        main_agent = SimpleNamespace()
        _bind_main_coordinator_methods(main_agent)

        async def fake_execute_turn_core(prompt: str, message_history=None, skip_plan_execution=True):
            _ = message_history
            _ = skip_plan_execution
            assert "coordinator planner" in prompt
            return "- Use existing skills first\n- Verify changed files"

        main_agent._execute_turn_core = fake_execute_turn_core

        plan = await main_agent._coordinator_make_or_update_plan(
            SimpleNamespace(userRequest="請修復 bug", taskKind="bugfix")
        )

        assert plan.type == "spawn-worker"
        assert plan.workerSpec is not None
        assert "[Coordinator guidance from main]" in plan.workerSpec.instruction
        assert "Use existing skills first" in plan.workerSpec.instruction

    asyncio.run(scenario())


def test_question_task_kind_always_answers_directly():
    async def scenario() -> None:
        main_agent = SimpleNamespace()
        _bind_main_coordinator_methods(main_agent)

        async def fake_execute_turn_core(prompt: str, message_history=None, skip_plan_execution=True):
            _ = message_history
            _ = skip_plan_execution
            return f"direct:{prompt}"

        main_agent._execute_turn_core = fake_execute_turn_core

        plan = await main_agent._coordinator_make_or_update_plan(
            SimpleNamespace(userRequest="請介紹這個架構", taskKind="question")
        )

        assert plan.type == "answer-directly"
        assert plan.finalAnswer.startswith("direct:")

    asyncio.run(scenario())
