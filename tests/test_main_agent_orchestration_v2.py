import asyncio
from types import SimpleNamespace

import pytest

from internal.agents import main_agent as main_agent_module
from internal.agents.main_agent import MainAgent


def _bind_methods(fake_main: object) -> None:
    bound_method_names = [
        "_coordinator_infer_task_kind",
        "_coordinator_looks_like_direct_question",
        "_coordinator_should_decompose_todos",
        "_coordinator_extract_todo_steps",
        "_coordinator_build_worker_specs",
        "_coordinator_make_or_update_plan",
        "_coordinator_spawn_worker",
        "_coordinator_spawn_verification",
        "_coordinator_augment_context_with_failure",
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

    plan = fake_main._orchestration_parse_plan_json("not-json", "implementation", "fix the bug")

    assert plan.taskKind == "implementation"
    assert len(plan.steps) == 1
    assert plan.steps[0].kind == "implement"
    assert plan.steps[0].goal == "fix the bug"


def test_question_fast_lane_skips_orchestration_runtime():
    async def scenario() -> None:
        fake_main = SimpleNamespace()
        _bind_methods(fake_main)

        async def fake_execute_turn_core(prompt: str, message_history=None, skip_plan_execution=True):
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

        def fail_plan(*args, **kwargs):
            raise AssertionError("planner should not run for greeting")

        fake_main._execute_turn_core = fake_execute_turn_core
        fake_main._coordinator_make_or_update_plan = fail_plan
        fake_main._coordinator_spawn_worker = fail_plan
        fake_main._coordinator_spawn_verification = fail_plan
        fake_main._coordinator_augment_context_with_failure = fail_plan

        text = await fake_main.coordinator_handle_user_turn("hello there")

        assert text == "direct:hello there"
        assert fake_main._coordinator_looks_like_direct_question("hello there") is True

    asyncio.run(scenario())


def test_implementation_turn_uses_legacy_coordinator_flow(monkeypatch: pytest.MonkeyPatch):
    async def scenario() -> None:
        fake_main = SimpleNamespace()
        _bind_methods(fake_main)
        fake_main._execute_turn_core = None

        recorded: dict[str, str] = {}

        async def fake_run_coordinator_turn(ctx, **kwargs):
            recorded["userRequest"] = ctx.userRequest
            recorded["taskKind"] = ctx.taskKind
            return "legacy-flow"

        monkeypatch.setattr(main_agent_module, "run_coordinator_turn", fake_run_coordinator_turn)

        text = await fake_main.coordinator_handle_user_turn("fix this bug")

        assert text == "legacy-flow"
        assert recorded == {
            "userRequest": "fix this bug",
            "taskKind": "bugfix",
        }

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


def test_small_implementation_plan_skips_planner_calls():
    async def scenario() -> None:
        fake_main = SimpleNamespace()
        _bind_methods(fake_main)

        def fail(*args, **kwargs):
            raise AssertionError("planner LLM path should not run")

        fake_main._coordinator_generate_main_guidance = fail
        fake_main._coordinator_generate_todo_breakdown = fail
        fake_main._build_planning_instruction = lambda user_request: f"plan:{user_request}"
        fake_main._coordinator_should_run_background = lambda _prompt: False

        plan = await fake_main._coordinator_make_or_update_plan(
            main_agent_module.CoordinatorTurnContext(
                userRequest="fix the failing test",
                taskKind="bugfix",
            )
        )

        assert plan.type == "spawn-worker"
        assert plan.workerSpec is not None
        assert plan.workerSpec.title == "implementation-task"
        assert len(plan.workerSpecs) == 1

    asyncio.run(scenario())


def test_large_implementation_plan_decomposes_into_multiple_todos():
    async def scenario() -> None:
        fake_main = SimpleNamespace()
        _bind_methods(fake_main)
        fake_main._build_planning_instruction = lambda user_request: f"plan:{user_request}"
        fake_main._coordinator_should_run_background = lambda _prompt: False

        plan = await fake_main._coordinator_make_or_update_plan(
            main_agent_module.CoordinatorTurnContext(
                userRequest="先找 root cause，再修 bug，最後補測試並驗證",
                taskKind="implementation",
            )
        )

        assert plan.type == "spawn-worker"
        assert len(plan.workerSpecs) >= 2
        assert all(spec.instruction.startswith("plan:") for spec in plan.workerSpecs)

    asyncio.run(scenario())


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
        main._follow_through_needs_retry = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("follow-through retry should not run")
        )

        text = await main._execute_turn_core("hello")

        assert text == "done"

    asyncio.run(scenario())
