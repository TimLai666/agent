from __future__ import annotations

from dataclasses import dataclass, field

from internal.core.agents.agent_types import SendMessageInput


@dataclass
class MessageBus:
    _messages: dict[str, list[str]] = field(default_factory=dict)

    def send(self, input_data: SendMessageInput) -> None:
        self._messages.setdefault(input_data.toTaskId, []).append(input_data.message)

    def drain(self, task_id: str) -> list[str]:
        return self._messages.pop(task_id, [])
