from __future__ import annotations

import inspect
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
        if inspect.iscoroutinefunction(tool):
            raise TypeError(
                f"Tool {tool_name!r} is async; use ToolExecutor.execute_async() or schedule via asyncio."
            )

        started_at = time.time()
        success = True
        output_summary = ""
        try:
            result = tool(*args, **kwargs)
            if inspect.iscoroutine(result):
                # Defensive: tool returned a coroutine (e.g. wrapping async). Refuse.
                try:
                    result.close()
                except Exception:
                    pass
                raise TypeError(
                    f"Tool {tool_name!r} returned a coroutine; sync ToolExecutor cannot await it."
                )
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

    async def execute_async(self, tool_name: str, *args: object, **kwargs: object) -> object:
        tool = self.registry.get(tool_name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_name}")

        started_at = time.time()
        success = True
        output_summary = ""
        try:
            result = tool(*args, **kwargs)
            if inspect.iscoroutine(result):
                result = await result
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
