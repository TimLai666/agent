from pydantic_ai import RunContext
from datetime import datetime
import random


def add_basic_tools(agent) -> None:
    """Add tools to the agent."""

    @agent.tool_plain
    def get_now() -> str:
        """Get the current time."""
        return datetime.now().isoformat()

    @agent.tool_plain
    def roll_dice() -> str:
        """Roll a six-sided die and return the result."""
        return str(random.randint(1, 6))
