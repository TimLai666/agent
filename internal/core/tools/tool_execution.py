from __future__ import annotations

import time
from dataclasses import dataclass

from internal.core.tools.tool_registry import ToolRegistry
from internal.core.tools.tool_usage_tracker import ToolUsageTracker


@dataclass
class ToolExecutor:
    registry: ToolRegistry
    tracker: ToolUsageTracker

    def execute(self, tool_name: str, *args: object, **kwargs: object) -> object:
        tool = self.registry.get(tool_name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_name}")

        started_at = time.time()
        success = True
        output_summary = ""
        try:
            result = tool(*args, **kwargs)
            output_summary = str(result)[:200]
            return result
        except Exception as exc:
            success = False
            output_summary = str(exc)
            raise
        finally:
            self.tracker.record(
                tool_name=tool_name,
                started_at=started_at,
                input_summary=f"args={len(args)}, kwargs={list(kwargs.keys())}",
                output_summary=output_summary,
                success=success,
            )
