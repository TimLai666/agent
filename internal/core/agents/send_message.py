from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from internal.core.agents.agent_types import SendMessageInput


@dataclass
class MessageBus:
    _messages: dict[str, list[str]] = field(default_factory=dict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def send(self, input_data: SendMessageInput) -> None:
        with self._lock:
            self._messages.setdefault(input_data.toTaskId, []).append(input_data.message)

    def drain(self, task_id: str) -> list[str]:
        with self._lock:
            return self._messages.pop(task_id, [])
