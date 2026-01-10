from pydantic_ai import Agent

from .tools.basic_tools import add_basic_tools
from .tools.file_tools import add_file_tools
from .tools.interactive_tools import add_interactive_tools
from .tools.python_tools import add_python_tools
from .tools.stock_market_tools import add_stock_market_tools
from .tools.terminal_tools import add_terminal_tools
from .tools.website_tools import add_website_tools


def add_all_tools(
    agent: Agent, model: str, base_url: str | None = None, api_key: str | None = None
) -> None:
    """Add tools to the agent."""

    add_basic_tools(agent)
    add_file_tools(agent)
    add_python_tools(agent)
    add_terminal_tools(agent)
    add_interactive_tools(agent)
    add_website_tools(agent, model=model, base_url=base_url, api_key=api_key)
    add_stock_market_tools(agent)
