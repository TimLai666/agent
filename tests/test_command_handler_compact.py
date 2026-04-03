from internal.command_handler import CommandHandler


class DummyAgent:
    pass


def test_compact_command_returns_control_signal():
    outputs: list[str] = []
    handler = CommandHandler(
        main_agent=DummyAgent(),
        history=[],
        output_callback=outputs.append,
    )

    result = handler.handle("/compact")

    assert result == "__compact__"
    assert outputs == []


def test_clear_command_returns_clear_context_signal():
    outputs: list[str] = []
    handler = CommandHandler(
        main_agent=DummyAgent(),
        history=[("u", "a")],
        output_callback=outputs.append,
    )

    result = handler.handle("/clear")

    assert result == "__clear_context__"
    assert outputs == []


def test_clear_context_state_resets_handler_context():
    handler = CommandHandler(
        main_agent=DummyAgent(),
        history=[("u", "a")],
        output_callback=lambda _text: None,
    )
    handler.update_last_prompt("hello")
    handler.update_last_reply("world")

    handler.clear_context_state()

    assert handler.history == []
    assert handler.last_user_prompt == ""
    assert handler.last_assistant_reply == ""
