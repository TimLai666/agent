from internal.services.circle_ui import CommandLineEdit


def test_compact_exists_in_command_autocomplete_list():
    assert "/compact" in CommandLineEdit.COMMANDS
