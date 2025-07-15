import os
from pydantic_ai import Agent


def add_file_tools(agent: Agent) -> None:
    """Add file-related tools to the agent."""

    file_tools_manager: FileTools = FileTools()

    @agent.tool_plain
    def get_current_directory() -> str:
        """Get the current working directory."""
        return file_tools_manager.get_current_directory()

    @agent.tool_plain
    def list_files_in_directory(dir: str) -> str:
        """List all files in the specified directory."""
        return file_tools_manager.list_files_in_directory(dir)

    @agent.tool_plain
    def read_file(file_path: str) -> str:
        """Read the contents of a file."""
        return file_tools_manager.read_file(file_path)

    @agent.tool_plain
    def make_new_directory(dir: str) -> str:
        """Create a new empty directory."""
        return file_tools_manager.make_new_directory(dir)

    @agent.tool_plain
    def create_new_file(file_path: str, content: str) -> str:
        """Create a new file with the content."""
        return file_tools_manager.create_new_file(file_path, content)


class FileTools:
    """A class to encapsulate file-related tools."""

    def __init__(self) -> None:
        self.base_path: str = os.getcwd()
        self.home_path: str = os.path.expanduser("~")

    def get_current_directory(self) -> str:
        return self.base_path

    def list_files_in_directory(self, dir: str) -> str:
        try:
            files: list[str] = os.listdir(dir)
            return ', '.join(files)
        except FileNotFoundError:
            return f"Directory '{dir}' not found."
        except Exception as e:
            return str(e)

    def read_file(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            return str(e)

    def make_new_directory(self, dir: str) -> str:
        try:
            if os.path.exists(dir):
                raise FileExistsError(f"Directory '{dir}' already exists.")
            os.makedirs(dir, exist_ok=True)
            return f"Directory '{dir}' created successfully."
        except Exception as e:
            return str(e)

    def create_new_file(self, file_path: str, content: str) -> str:
        try:
            if os.path.exists(file_path):
                raise FileExistsError(f"File '{file_path}' already exists.")
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(content)
            return f"File '{file_path}' created successfully."
        except Exception as e:
            return str(e)
