import os
from pydantic_ai import Agent

from internal.cli import confirm
from internal.logger import logger


def add_file_tools(agent: Agent) -> None:
    """Add file-related tools to the agent."""

    file_tools_manager: FileTools = FileTools()

    @agent.tool_plain
    def get_current_directory() -> str:
        """Get the current working directory."""
        return file_tools_manager.get_current_directory()

    @agent.tool_plain
    def get_home_directory() -> str:
        """Get the home directory."""
        return file_tools_manager.get_home_directory()

    @agent.tool_plain
    def get_desktop_directory() -> str:
        """Get the desktop directory."""
        return file_tools_manager.get_desktop_directory()

    @agent.tool_plain
    def list_files_in_directory(dir: str) -> str:
        """List all files in the specified directory."""
        return file_tools_manager.list_files_in_directory(dir)

    @agent.tool_plain
    def find_files_with_fragment(fragment_regx: str, files: list[str]) -> list[str]:
        """Find files containing a specific fragment in their names.

        Parameters:
            fragment_regx (str): The fragment to search for (in regular expression).
            files (list[str]): The list of files to search within.

        Returns:
            list[str]: A list of matching file names.
        """
        return file_tools_manager.find_files_with_fragment(fragment_regx, files)

    @agent.tool_plain
    def find_all_lines_in_file_with_fragment(fragment_regx: str, file_path: str) -> list[str]:
        """Find all lines in a file that contain a specific fragment.

        Parameters:
            fragment_regx (str): The fragment to search for (in regular expression).
            file_path (str): The path to the file to search within.

        Returns:
            list[str]: A list of matching lines.
        """
        return file_tools_manager.find_all_lines_in_file_with_fragment(fragment_regx, file_path)

    @agent.tool_plain
    def read_file(file_path: str) -> str:
        """Read the contents of a file."""
        return file_tools_manager.read_file(file_path)

    @agent.tool_plain
    def modify_existing_file(file_path: str, content: str) -> str:
        """Modify an existing file with new content."""
        return file_tools_manager.modify_existing_file(file_path, content)

    @agent.tool_plain
    def rename_file_or_directory(path: str, new_name: str) -> str:
        """Rename a file or directory. new_name should not include the path."""
        return file_tools_manager.rename_file_or_directory(path, new_name)

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
        self.desktop_path: str = os.path.join(self.home_path, "Desktop")

    def get_current_directory(self) -> str:
        logger.info(f"Getting current directory")
        return self.base_path

    def get_home_directory(self) -> str:
        logger.info(f"Getting home directory")
        return self.home_path

    def get_desktop_directory(self) -> str:
        logger.info(f"Getting desktop directory")
        return self.desktop_path

    def list_files_in_directory(self, dir: str) -> str:
        logger.info(f"Listing files in directory: {dir}")
        try:
            files: list[str] = os.listdir(dir)
            return ', '.join(files)
        except FileNotFoundError:
            return f"Directory '{dir}' not found."
        except Exception as e:
            logger.error(f"Error listing files in directory {dir}: {str(e)}")
            return str(e)

    def find_files_with_fragment(self, fragment_regx: str, files: list[str]) -> list[str]:
        logger.info(
            f"Finding matches in {files} with fragment: {fragment_regx}")
        try:
            matching_files = [f for f in files if fragment_regx in f]
            if not matching_files:
                return [f"No files found containing '{fragment_regx}'."]
            return matching_files
        except Exception as e:
            logger.error(
                f"Error finding files with fragment {fragment_regx}: {str(e)}")
            return [str(e)]

    def find_all_lines_in_file_with_fragment(self, fragment_regx: str, file_path: str) -> list[str]:
        logger.info(
            f"Finding all lines in file with fragment: {fragment_regx}")
        try:
            content = self.read_file(file_path)
            if not content:
                return [f"File '{file_path}' is empty or not found."]
            matches = [line for line in content.splitlines()
                       if fragment_regx in line]
            if not matches:
                return [f"No matches found in file '{file_path}' for fragment: {fragment_regx}"]
            return matches
        except Exception as e:
            logger.error(
                f"Error finding fragment in file {file_path}: {str(e)}")
            return [str(e)]

    def read_file(self, file_path: str) -> str:
        logger.info(f"Reading file: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {str(e)}")
            return str(e)

    def modify_existing_file(self, file_path: str, content: str) -> str:
        try:
            if not confirm(
                message=f"Agent wants to modify file '{file_path}', allow?",
                default_choice='Y'
            ):
                raise PermissionError("File modification cancelled by user.")
            logger.info(f"Modifying file: {file_path}")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File '{file_path}' does not exist.")
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(content)
            return f"File '{file_path}' modified successfully."
        except FileNotFoundError:
            return f"File '{file_path}' not found."
        except Exception as e:
            logger.error(f"Error modifying file {file_path}: {str(e)}")
            return str(e)

    def rename_file_or_directory(self, path: str, new_name: str) -> str:
        try:
            if not confirm(
                message=f"Agent wants to rename '{path}' to '{new_name}', allow?",
                default_choice='Y'
            ):
                raise PermissionError("File renaming cancelled by user.")
            logger.info(f"Renaming '{path}' to '{new_name}'")
            if not os.path.exists(path):
                raise FileNotFoundError(f"File '{path}' does not exist.")
            new_file_path = os.path.join(os.path.dirname(path), new_name)
            os.rename(path, new_file_path)
            return f"File renamed to '{new_file_path}' successfully."
        except FileNotFoundError:
            return f"File '{path}' not found."
        except Exception as e:
            logger.error(f"Error renaming file {path}: {str(e)}")
            return str(e)

    def make_new_directory(self, dir: str) -> str:
        try:
            if not confirm(
                message=f"Agent wants to create a new directory '{dir}', allow?",
                default_choice='Y'
            ):
                raise PermissionError("Directory creation cancelled by user.")
            logger.info(f"Creating new directory: {dir}")
            if os.path.exists(dir):
                raise FileExistsError(f"Directory '{dir}' already exists.")
            os.makedirs(dir, exist_ok=True)
            return f"Directory '{dir}' created successfully."
        except Exception as e:
            logger.error(f"Error creating directory {dir}: {str(e)}")
            return str(e)

    def create_new_file(self, file_path: str, content: str) -> str:
        try:
            if not confirm(
                message=f"Agent wants to create a new file at '{file_path}', allow?",
                default_choice='Y'
            ):
                raise PermissionError("File creation cancelled by user.")
            logger.info(f"Creating new file: {file_path}")
            if os.path.exists(file_path):
                raise FileExistsError(f"File '{file_path}' already exists.")
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(content)
            return f"File '{file_path}' created successfully."
        except Exception as e:
            logger.error(f"Error creating file {file_path}: {str(e)}")
            return str(e)
