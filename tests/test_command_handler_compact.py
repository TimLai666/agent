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
