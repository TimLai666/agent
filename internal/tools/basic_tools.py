from pydantic_ai import Agent
from datetime import datetime
import random


def add_basic_tools(agent: Agent) -> None:
    """Add tools to the agent."""

    @agent.tool_plain
    def get_now() -> str:
        """Get the current time."""
        return datetime.now().isoformat()

    @agent.tool_plain
    def roll_dice() -> str:
        """Roll a six-sided die and return the result."""
        return str(random.randint(1, 6))

    @agent.tool_plain
    def random_pick(items: list[str]) -> str:
        """Randomly pick an item from the provided list."""
        if not items:
            return "No items provided."
        return random.choice(items)
