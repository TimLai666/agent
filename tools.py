
def add_tools(agent) -> None:
    """Add tools to the agent."""

    @agent.tool_plain
    def roll_dice() -> str:
        """Roll a six-sided die and return the result."""
        return str(random.randint(1, 6))

    @agent.tool
    def get_player_name(ctx: RunContext[str]) -> str:
        """Get the player's name."""
        return ctx.deps
