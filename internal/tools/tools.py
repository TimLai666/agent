from internal.tools.basic_tools import add_basic_tools
from internal.tools.file_tools import add_file_tools
from internal.tools.python_tools import add_python_tools
from internal.tools.interactive_tools import add_interactive_tools


def add_all_tools(agent) -> None:
    """Add tools to the agent."""

    add_basic_tools(agent)
    add_file_tools(agent)
    add_python_tools(agent)
    add_interactive_tools(agent)
