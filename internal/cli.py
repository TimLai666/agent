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
_gui_question_handler: Optional[Callable[[str, list[str], bool], str]] = None
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


def set_gui_question_handler(handler: Optional[Callable[[str, list[str], bool], str]]) -> None:
    """
    Set the GUI question handler for AskUserQuestion tool.

    Args:
        handler: A function that takes (question, options, multi) and returns the selected option string.
                 Set to None to use CLI mode.
    """
    global _gui_question_handler
    with _question_lock:
        _gui_question_handler = handler
        logger.info(f"GUI question handler {'set' if handler else 'cleared'}")


def ask_user_question(question: str, options: list[str], multi: bool = False) -> str:
    """
    Display a question (with optional options) to the user and return their answer.

    In GUI mode, shows a ChoiceDialog/inline bubble with option buttons or checkboxes.
    In CLI mode, prints the question and options to the terminal.

    Args:
        question: The question text.
        options: List of option strings. Empty list shows a free-text input.
        multi: If True, allows selecting multiple options (returns comma-separated).
    """
    with _question_lock:
        handler = _gui_question_handler
    logger.info(f"ask_user_question() called: question='{question[:60]}...', options={options}, multi={multi}")

    if handler is not None:
        result = handler(question, options, multi)
        logger.info(f"ask_user_question GUI result: {result!r}")
        return result

    # CLI fallback
    print(f"\n{question}")
    if options:
        hint = "（可輸入多個編號，以逗號分隔）" if multi else ""
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
        print(f"  {len(options) + 1}. 自訂輸入")
        if hint:
            print(hint)
        while True:
            try:
                raw = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                return options[0] if options else ""

            if multi:
                # Accept comma-separated indices or option texts
                parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
                selected = []
                custom_needed = False
                for part in parts:
                    try:
                        idx = int(part)
                        if idx == len(options) + 1:
                            custom_needed = True
                        elif 1 <= idx <= len(options):
                            selected.append(options[idx - 1])
                    except ValueError:
                        for opt in options:
                            if part.lower() == opt.lower():
                                selected.append(opt)
                                break
                if custom_needed:
                    try:
                        custom = input("請輸入自訂答案> ").strip()
                        if custom:
                            selected.append(custom)
                    except (EOFError, KeyboardInterrupt):
                        pass
                if selected:
                    return ", ".join(selected)
                print(f"請輸入有效的編號（1–{len(options) + 1}）。")
            else:
                # Single select
                try:
                    idx = int(raw)
                    if idx == len(options) + 1:
                        try:
                            return input("請輸入自訂答案> ").strip()
                        except (EOFError, KeyboardInterrupt):
                            return ""
                    if 1 <= idx <= len(options):
                        return options[idx - 1]
                except ValueError:
                    pass
                for opt in options:
                    if raw.lower() == opt.lower():
                        return opt
                print(f"Please enter a number (1–{len(options) + 1}) or the option text.")
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
