from __future__ import annotations

from dataclasses import dataclass

from internal.core.tasks.task_types import AgentType, WorkerResult


@dataclass
class BuiltInAgentDefinition:
    agentType: AgentType
    whenToUse: str
    tools: list[str] | None
    disallowedTools: list[str] | None
    systemPrompt: str


@dataclass
class SpawnWorkerInput:
    agentType: AgentType
    title: str
    originalUserRequest: str
    instruction: str
    runInBackground: bool = False
    model: str | None = None


@dataclass
class SpawnVerificationInput:
    originalUserRequest: str
    workerResult: WorkerResult
    filesChanged: list[str]
    approachSummary: str | None = None


@dataclass
class SendMessageInput:
    toTaskId: str
    message: str
