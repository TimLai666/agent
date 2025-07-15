from typing import Literal
import io


class TeeStdout(io.StringIO):
    """這個類別用於將輸出同時寫入多個流。"""

    def __init__(self, *streams) -> None:
        super().__init__()
        self.streams: tuple = streams

    def write(self, s) -> int:
        for stream in self.streams:
            stream.write(s)
        super().write(s)
        return len(s)

    def flush(self) -> None:
        for stream in self.streams:
            if hasattr(stream, "flush"):
                stream.flush()
        super().flush()


def confirm(message: str, default_choice: str = '') -> bool:
    """
    Display a confirmation message to the user.

    Args:
        message (str): The confirmation message to display.
        default_choice (str): The default choice if the user just presses Enter.
    """
    default_choice = default_choice.strip().upper()
    if default_choice not in ['Y', 'N', '']:
        raise ValueError(
            "default_choice must be 'Y', 'N', or an empty string.")
    yes_no_str: Literal['[y/n]'] | Literal['[Y/n]'] | Literal['[y/N]'] = "[y/n]" if not default_choice else "[Y/n]" if default_choice == 'Y' else "[y/N]"
    response: str = r if (r := input(
        f"<Confirmation> {message} {yes_no_str}: ")) else default_choice

    while True:
        if response == '':
            response = input(
                f"Please enter a valid response: {message}{yes_no_str}")
        if response.upper() in ['Y', 'N']:
            return response.upper() == 'Y'
