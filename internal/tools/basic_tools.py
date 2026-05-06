import asyncio
import random
from pydantic_ai import Agent

from internal.logger import logger


_MAX_TIMEOUT_SECONDS = 300


def add_basic_tools(agent: Agent) -> None:
    """Add basic tools to the agent."""

    @agent.tool_plain
    def roll_dice() -> str:
        """Roll a six-sided die and return the result."""
        return str(random.randint(1, 6))

    @agent.tool_plain
    def random_pick(items: list[str]) -> str:
        """Randomly pick an item from the provided list."""
        logger.info(f"Randomly picking from items: {items}")
        if not items:
            return "No items provided."
        return random.choice(items)

    @agent.tool_plain
    async def timeout(seconds: int) -> str:
        """Wait for a specified number of seconds (capped at 300s, max). Async-safe."""
        if seconds < 0:
            return "Cannot wait for negative time."
        if seconds > _MAX_TIMEOUT_SECONDS:
            logger.warning(
                "timeout(%s) capped to %s seconds.", seconds, _MAX_TIMEOUT_SECONDS
            )
            seconds = _MAX_TIMEOUT_SECONDS
        logger.info(f"Start waiting for {seconds} seconds...")
        await asyncio.sleep(seconds)
        logger.info("Wait completed.")
        return f"Time's up after {seconds} seconds."
