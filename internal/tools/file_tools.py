import os
from pydantic_ai import RunContext


def add_file_tools(agent) -> None:
    """Add file-related tools to the agent."""

    @agent.tool_plain
    def get_current_directory() -> str:
        """Get the current working directory."""
        return os.getcwd()

    @agent.tool_plain
    def list_files_in_directory(dir: str) -> str:
        """List all files in the specified directory."""
        try:
            files = os.listdir(dir)
            return ', '.join(files)
        except FileNotFoundError:
            return f"Directory '{dir}' not found."
        except Exception as e:
            return str(e)
