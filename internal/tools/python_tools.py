import io
import os
import sys
from pydantic_ai import Agent
from typing import TextIO, Any

from internal.cli import TeeStdout, confirm


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
                default_choice='Y'
            ):
                raise PermissionError("Script execution cancelled by user.")
            old_stdout: TextIO | Any = sys.stdout
            buffer: io.StringIO = io.StringIO()
            sys.stdout = TeeStdout(old_stdout, buffer)
            try:
                exec(script)
            finally:
                sys.stdout = old_stdout
            output: str = buffer.getvalue()
            return output if output else "Script executed successfully."
        except Exception as e:
            return f"Error executing script: {str(e)}"
