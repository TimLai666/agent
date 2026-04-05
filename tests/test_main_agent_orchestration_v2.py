import asyncio
from types import SimpleNamespace

import pytest

from internal.agents import main_agent as main_agent_module
from internal.agents.main_agent import MainAgent


def _bind_methods(fake_main: object) -> None:
    bound_method_names = [
        "coordinator_handle_user_turn",
        "_orchestration_build_task_graph",
        "_orchestration_parse_plan_json",
    ]
    static_method_names = [
        "_orchestration_default_contract",
        "_orchestration_default_recovery_policy",
        "_orchestration_step_kind_for_task",
    ]
    for method_name in bound_method_names:
        method = getattr(MainAgent, method_name)
        setattr(fake_main, method_name, method.__get__(fake_main, type(fake_main)))
    for method_name in static_method_names:
        setattr(fake_main, method_name, getattr(MainAgent, method_name))


def test_orchestration_parse_plan_json_falls_back_to_single_step():
    fake_main = SimpleNamespace()
    _bind_methods(fake_main)

    plan = fake_main._orchestration_parse_plan_json(
        "not-json",
        "implementation",
        "fix the bug",
    )

    assert plan.taskKind == "implementation"
    assert len(plan.steps) == 1
    assert plan.steps[0].kind == "implement"
    assert plan.steps[0].goal == "fix the bug"


def test_question_fast_lane_skips_orchestration_runtime():
    async def scenario() -> None:
        fake_main = SimpleNamespace()
        _bind_methods(fake_main)

        async def fake_execute_turn_core(
            prompt: str,
            message_history=None,
            skip_plan_execution=True,
        ):
            _ = message_history
            _ = skip_plan_execution
            return f"direct:{prompt}"

        class FailRuntime:
            async def execute(self, *args, **kwargs):
                raise AssertionError("runtime should not run for direct question")

        fake_main._execute_turn_core = fake_execute_turn_core
        fake_main._orchestration_runtime = FailRuntime()

        text = await fake_main.coordinator_handle_user_turn("What is this system?")

        assert text.startswith("direct:What is this system?")

    asyncio.run(scenario())


def test_greeting_fast_lane_answers_directly_without_planner():
    async def scenario() -> None:
        fake_main = SimpleNamespace()
        _bind_methods(fake_main)

        async def fake_execute_turn_core(
            prompt: str,
            message_history=None,
            skip_plan_execution=True,
        ):
            _ = message_history
            _ = skip_plan_execution
            return f"direct:{prompt}"

        fake_main._execute_turn_core = fake_execute_turn_core

        text = await fake_main.coordinator_handle_user_turn("hello there")

        assert text == "direct:hello there"

    asyncio.run(scenario())


def test_implementation_turn_uses_main_agent_execution_core():
    async def scenario() -> None:
        fake_main = SimpleNamespace()
        _bind_methods(fake_main)

        async def fake_execute_turn_core(
            prompt: str,
            message_history=None,
            skip_plan_execution=True,
        ):
            _ = message_history
            _ = skip_plan_execution
            return f"handled:{prompt}"

        fake_main._execute_turn_core = fake_execute_turn_core

        text = await fake_main.coordinator_handle_user_turn("fix this bug")

        assert text == "handled:fix this bug"

    asyncio.run(scenario())


def test_hot_path_does_not_use_legacy_keyword_routing():
    async def scenario() -> None:
        fake_main = SimpleNamespace()
        _bind_methods(fake_main)

        async def fake_execute_turn_core(
            prompt: str,
            message_history=None,
            skip_plan_execution=True,
        ):
            _ = message_history
            _ = skip_plan_execution
            return f"handled:{prompt}"

        fake_main._execute_turn_core = fake_execute_turn_core

        text = await fake_main.coordinator_handle_user_turn(
            "去網路上找5個主題的文章並總結"
        )

        assert text == "handled:去網路上找5個主題的文章並總結"

    asyncio.run(scenario())


def test_main_agent_init_does_not_construct_orchestration_runtime(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_store():
        raise AssertionError("orchestration store should stay disabled at init")

    def fail_runtime(*args, **kwargs):
        raise AssertionError("orchestration runtime should stay disabled at init")

    monkeypatch.setattr(main_agent_module, "OrchestrationStore", fail_store)
    monkeypatch.setattr(main_agent_module, "OrchestrationRuntime", fail_runtime)

    agent = SimpleNamespace()
    main = MainAgent(agent)

    assert main.resume_incomplete_runs() == []
    assert main.orchestration_store is None


def test_main_agent_removes_legacy_coordinator_heuristics():
    removed_method_names = [
        "_build_planning_instruction",
        "_coordinator_infer_task_kind",
        "_coordinator_looks_like_direct_question",
        "_coordinator_should_decompose_todos",
        "_coordinator_extract_todo_steps",
        "_coordinator_make_worker_title",
        "_coordinator_build_worker_specs",
        "_coordinator_make_or_update_plan",
        "_coordinator_spawn_worker",
        "_coordinator_spawn_verification",
        "_coordinator_augment_context_with_failure",
        "_coordinator_should_run_background",
    ]

    for method_name in removed_method_names:
        assert not hasattr(MainAgent, method_name), method_name


def test_execute_turn_core_does_not_run_follow_through_retry():
    async def scenario() -> None:
        fake_result = SimpleNamespace(
            output="done",
            all_messages=lambda: [],
        )
        fake_agent = SimpleNamespace(
            run=lambda *args, **kwargs: asyncio.sleep(0, result=fake_result),
        )

        main = MainAgent(fake_agent)
        main._follow_through_needs_retry = lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("follow-through retry should not run"))

        text = await main._execute_turn_core("hello")

        assert text == "done"

    asyncio.run(scenario())
