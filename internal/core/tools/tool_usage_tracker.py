from __future__ import annotations

import time
from dataclasses import dataclass, field

from internal.core.tasks.task_types import ToolExecutionRecord


@dataclass
class ToolUsageTracker:
    records: list[ToolExecutionRecord] = field(default_factory=list)

    def record(
        self,
        *,
        tool_name: str,
        started_at: float,
        input_summary: str,
        output_summary: str,
        success: bool,
    ) -> None:
        self.records.append(
            ToolExecutionRecord(
                toolName=tool_name,
                startedAt=int(started_at * 1000),
                finishedAt=int(time.time() * 1000),
                inputSummary=input_summary,
                outputSummary=output_summary,
                success=success,
            )
        )
