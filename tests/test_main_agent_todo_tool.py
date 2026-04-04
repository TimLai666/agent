from __future__ import annotations

from internal.agents.main_agent import MainAgent


class _FakeAgent:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool_plain(self, func=None, /, **kwargs):
        _ = kwargs
        if func is None:
            def decorator(inner):
                self.tools[inner.__name__] = inner
                return inner
            return decorator
        self.tools[func.__name__] = func
        return func


def test_register_todo_tool_updates_snapshot_and_callback():
    fake_agent = _FakeAgent()
    main = MainAgent(fake_agent)  # type: ignore[arg-type]
    snapshots: list[str] = []
    main._active_todo_update_callback = snapshots.append

    main._register_todo_tools()

    todo_tool = fake_agent.tools["todo"]
    result = todo_tool(
        phase="executing",
        items=[
            {
                "id": "todo_001",
                "title": "Inspect logs",
                "status": "in_progress",
                "notes": "Looking at recent failures",
            },
            {
                "id": "todo_002",
                "title": "Fix bug",
                "status": "pending",
            },
        ],
    )

    assert "[TODO] phase=executing" in result
    assert "Inspect logs" in result
    assert snapshots == [result]
    assert main._todo_tool_snapshot == result
    assert len(main._todo_tool_items) == 2


def test_register_todo_tool_can_clear_snapshot():
    fake_agent = _FakeAgent()
    main = MainAgent(fake_agent)  # type: ignore[arg-type]
    snapshots: list[str] = []
    main._active_todo_update_callback = snapshots.append

    main._register_todo_tools()
    todo_tool = fake_agent.tools["todo"]

    result = todo_tool(phase="completed", items=[])

    assert result == "[TODO] phase=completed\n- (empty)"
    assert main._todo_tool_items == []
    assert snapshots[-1] == result


def test_todo_snapshot_is_injected_into_prompt():
    fake_agent = _FakeAgent()
    main = MainAgent(fake_agent)  # type: ignore[arg-type]
    main._publish_todo_snapshot(
        "[TODO] phase=executing\n- todo_001 [in_progress] Inspect logs",
        [{"id": "todo_001", "title": "Inspect logs", "status": "in_progress"}],
        emit=False,
    )

    prompt = main._inject_todo_snapshot("User request here")

    assert "<active-session-todos>" in prompt
    assert "Use the `todo` tool" in prompt
    assert "Inspect logs" in prompt
    assert prompt.endswith("User request here")
