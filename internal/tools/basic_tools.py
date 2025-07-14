from pydantic_ai import Agent
from datetime import datetime
import random
import time


def add_basic_tools(agent: Agent) -> None:
    """Add tools to the agent."""

    @agent.tool_plain
    def get_now() -> str:
        """Get the current time."""
        return datetime.now().isoformat()

    @agent.tool_plain
    def get_weekday(date_str: str) -> str:
        """Get the weekday of a given date in English."""
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            return date_obj.strftime("%A")  # e.g., "Monday"
        except ValueError:
            return "Invalid date format. Please use YYYY-MM-DD."

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

    @agent.tool_plain
    def timeout(seconds: int) -> str:
        """Wait for a specified number of seconds."""
        if seconds < 0:
            return "Cannot wait for negative time."
        print(f"Start waiting for {seconds} seconds...")
        time.sleep(seconds)
        print("Wait completed.")
        # todo: 可以接個好看ui或鈴聲之類
        return f"Time's up after {seconds} seconds."
