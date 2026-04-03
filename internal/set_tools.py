from collections.abc import Callable
from pydantic_ai import Agent

from .tools.file_tools import add_file_tools
from .tools.stock_market_tools import add_stock_market_tools
from .tools.terminal_tools import add_terminal_tools
from .tools.web_search_tools import add_web_search_tools


def add_all_tools(
    agent: Agent,
    extra_tools: list[Callable] | None = None,
) -> None:
    """Add tools to the agent."""

    add_file_tools(agent)
    add_terminal_tools(agent)
    add_web_search_tools(agent)
    add_stock_market_tools(agent)
    if extra_tools:
        for tool in extra_tools:
            agent.tool_plain(tool)
