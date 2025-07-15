import os
import sys
from pydantic_ai import Agent


def add_python_tools(agent: Agent) -> None:
    """Add Python-related tools to the agent."""

    @agent.tool_plain
    def get_python_version() -> str:
        """Get the current Python version."""
        return f"Python {sys.version}"

    @agent.tool_plain
    def run_python_script(script: str) -> str:
        """Run a Python script and return its output."""
        try:
            exec(script)
            return "Script executed successfully."
        except Exception as e:
            return f"Error executing script: {str(e)}"
