from pydantic_ai import Agent

from internal.tools.basic_tools import add_basic_tools
from internal.tools.file_tools import add_file_tools
from internal.tools.python_tools import add_python_tools
from internal.tools.interactive_tools import add_interactive_tools
from internal.tools.website_tools import add_website_tools
from internal.tools.stock_market_tools import add_stock_market_tools


def add_all_tools(agent: Agent) -> None:
    """Add tools to the agent."""

    add_basic_tools(agent)
    add_file_tools(agent)
    add_python_tools(agent)
    add_interactive_tools(agent)
    add_website_tools(agent)
    add_stock_market_tools(agent)
