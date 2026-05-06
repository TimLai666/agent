import io
import sys
import threading
from typing import Any, TextIO

from pydantic_ai import Agent

from internal.cli import TeeStdout, confirm
from internal.logger import logger


_PYTHON_EXEC_LOCK = threading.Lock()


def add_python_tools(agent: Agent) -> None:
    """Add Python-related tools to the agent."""

    @agent.tool_plain
    def get_python_version() -> str:
        """Get the current Python version."""
        return f"Python {sys.version}"

    @agent.tool_plain
    def run_python_script(script: str, description: str) -> str:
        """Run a Python script and return its output"""
        try:
            if not confirm(
                message=f"Agent wants to run Python script({description}), allow?",
                default_choice="N",
            ):
                logger.info(f"User denied script execution: {description}")
                raise PermissionError(
                    "User denied permission to execute this script. The operation was cancelled."
                )

            buffer = io.StringIO()
            err_buffer = io.StringIO()
            with _PYTHON_EXEC_LOCK:
                old_stdout: TextIO | Any = sys.stdout
                old_stderr: TextIO | Any = sys.stderr
                sys.stdout = TeeStdout(old_stdout, buffer)
                sys.stderr = TeeStdout(old_stderr, err_buffer)
                try:
                    exec(script, {"__name__": "__main__"})
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr
            output = buffer.getvalue()
            err_output = err_buffer.getvalue()
            parts: list[str] = []
            if output:
                parts.append(output)
            if err_output:
                parts.append(f"--- stderr ---\n{err_output}")
            return "\n".join(parts) if parts else "Script executed successfully."
        except Exception as e:
            return f"Error executing script: {str(e)}"
