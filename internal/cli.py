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

# Global question handler for GUI mode
_gui_question_handler: Optional[Callable[[str, list[str]], str]] = None
_question_lock = threading.Lock()


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


def set_gui_question_handler(handler: Optional[Callable[[str, list[str]], str]]) -> None:
    """
    Set the GUI question handler for AskUserQuestion tool.

    Args:
        handler: A function that takes (question, options) and returns the selected option string.
                 Set to None to use CLI mode.
    """
    global _gui_question_handler
    with _question_lock:
        _gui_question_handler = handler
        logger.info(f"GUI question handler {'set' if handler else 'cleared'}")


def ask_user_question(question: str, options: list[str]) -> str:
    """
    Display a question (with optional options) to the user and return their answer.

    In GUI mode, shows a ChoiceDialog with clickable option buttons.
    In CLI mode, prints the question and options to the terminal.
    """
    with _question_lock:
        handler = _gui_question_handler
    logger.info(f"ask_user_question() called: question='{question[:60]}...', options={options}")

    if handler is not None:
        result = handler(question, options)
        logger.info(f"ask_user_question GUI result: {result!r}")
        return result

    # CLI fallback
    print(f"\n{question}")
    if options:
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
        while True:
            try:
                raw = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                return options[0] if options else ""
            try:
                idx = int(raw)
                if 1 <= idx <= len(options):
                    return options[idx - 1]
            except ValueError:
                pass
            for opt in options:
                if raw.lower() == opt.lower():
                    return opt
            print(f"Please enter a number (1–{len(options)}) or the option text.")
    else:
        try:
            return input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""


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
