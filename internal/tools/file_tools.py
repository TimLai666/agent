import os


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
            files: list[str] = os.listdir(dir)
            return ', '.join(files)
        except FileNotFoundError:
            return f"Directory '{dir}' not found."
        except Exception as e:
            return str(e)

    @agent.tool_plain
    def read_file(file_path: str) -> str:
        """Read the contents of a file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            return str(e)

    @agent.tool_plain
    def make_new_directory(dir: str) -> str:
        """Create a new empty directory."""
        try:
            if os.path.exists(dir):
                raise FileExistsError(f"Directory '{dir}' already exists.")
            os.makedirs(dir, exist_ok=True)
            return f"Directory '{dir}' created successfully."
        except Exception as e:
            return str(e)

    @agent.tool_plain
    def create_new_file(file_path: str, content: str) -> str:
        """Create a new file with the content."""
        try:
            if os.path.exists(file_path):
                raise FileExistsError(f"File '{file_path}' already exists.")
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(content)
            return f"File '{file_path}' created successfully."
        except Exception as e:
            return str(e)
