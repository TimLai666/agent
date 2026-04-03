from __future__ import annotations

from dataclasses import dataclass, field

from internal.core.tasks.task_types import SessionMode


@dataclass
class SessionContext:
    sessionId: str
    mode: SessionMode
    userRequest: str
    notifications: list[str] = field(default_factory=list)
