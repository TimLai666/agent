from zoneinfo import ZoneInfo
from pydantic_ai import Agent
from datetime import datetime, timedelta
from typing import Literal
import random
import time
import tzlocal


def add_basic_tools(agent: Agent) -> None:
    """Add tools to the agent."""

    @agent.tool_plain
    def get_now() -> str:
        """Get the current time with timezone info (local time, with UTC offset)."""
        now: datetime | None = None
        try:
            local_tz: ZoneInfo = tzlocal.get_localzone()
            now = datetime.now(local_tz)
            # 取得 UTC offset
            offset: timedelta | None = now.utcoffset()
            offset_str: str = ""
            if offset is not None:
                total_minutes: float = offset.total_seconds() / 60
                hours = int(total_minutes // 60)
                minutes = int(abs(total_minutes) % 60)
                sign: Literal['+'] | Literal['-'] = '+' if hours >= 0 else '-'
                offset_str = f"UTC{sign}{abs(hours):02d}:{minutes:02d}"
            else:
                offset_str = "UTC+00:00"
            return f"{now.isoformat()} ({local_tz}, {offset_str})"
        except ImportError:
            now = datetime.now()
            return f"{now.isoformat()} (timezone info unavailable)"

    @agent.tool_plain
    def get_weekday(date_str: str) -> str:
        """Get the weekday of a given date in English."""
        # 去除括號及其內容（如時區資訊），只保留日期部分
        if '(' in date_str:
            date_str = date_str.split('(')[0].strip()
        try:
            date_obj: datetime = datetime.strptime(date_str, "%Y-%m-%d")
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
