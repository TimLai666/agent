from typing import Literal, Callable, Optional
import io
import threading

from internal.logger import logger


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


# Global confirmation handler for GUI mode
_gui_confirm_handler: Optional[Callable[[str, str], bool]] = None
_confirm_lock = threading.Lock()


def set_gui_confirm_handler(handler: Optional[Callable[[str, str], bool]]) -> None:
    """
    Set the GUI confirmation handler for tool execution confirmation.
    
    Args:
        handler: A function that takes (message, default_choice) and returns bool.
                 Set to None to use CLI mode.
    """
    global _gui_confirm_handler
    with _confirm_lock:
        _gui_confirm_handler = handler
        logger.info(f"GUI confirm handler {'set' if handler else 'cleared'}")


def confirm(message: str, default_choice: str = '') -> bool:
    """
    Display a confirmation message to the user.
    
    In CLI mode, this uses terminal input().
    In GUI mode (if handler is set), this calls the GUI dialog.

    Args:
        message (str): The confirmation message to display.
        default_choice (str): The default choice if the user just presses Enter.
    """
    default_choice = default_choice.strip().upper()
    if default_choice not in ['Y', 'N', '']:
        raise ValueError(
            "default_choice must be 'Y', 'N', or an empty string.")
    
    # Check if we have a GUI handler
    with _confirm_lock:
        handler = _gui_confirm_handler
    logger.info(f"confirm() called: message='{message[:50]}...', GUI_mode={handler is not None}")
    
    if handler is not None:
        # Use GUI mode
        logger.info("Calling GUI confirm handler...")
        result = handler(message, default_choice)
        logger.info(f"GUI confirm result: {result}")
        return result
        return handler(message, default_choice)
    
    # Use CLI mode
    yes_no_str: Literal['[y/n]'] | Literal['[Y/n]'] | Literal['[y/N]'] = "[y/n]" if not default_choice else "[Y/n]" if default_choice == 'Y' else "[y/N]"
    response: str = r if (r := input(
        f"<Confirmation> {message} {yes_no_str}: ")) else default_choice

    while True:
        if response == '':
            response = input(
                f"Please enter a valid response: {message}{yes_no_str}")
        if response.upper() in ['Y', 'N']:
            return response.upper() == 'Y'
