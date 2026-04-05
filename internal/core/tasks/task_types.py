from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SessionMode = Literal["coordinator"]
TaskStatus = Literal["pending", "running", "completed", "failed", "killed"]
AgentType = Literal["general-purpose", "research", "implementation", "verification"]
TaskKind = Literal["question", "research", "implementation", "bugfix", "infra"]
VerificationVerdict = Literal["PASS", "FAIL", "PARTIAL"]
RunStatus = Literal["planning", "executing", "validating", "finalizing", "completed", "blocked", "failed"]
TodoStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "blocked",
    "failed",
    "impossible",
    "not_applicable",
    "retrying",
]
TodoPriority = Literal["high", "medium", "low"]


@dataclass
class TaskUsage:
    inputTokens: int | None = None
    outputTokens: int | None = None
    cacheCreationInputTokens: int | None = None
    cacheReadInputTokens: int | None = None
    durationMs: int | None = None


@dataclass
class ToolExecutionRecord:
    toolName: str
    startedAt: int
    finishedAt: int
    inputSummary: str
    outputSummary: str
    success: bool


@dataclass
class TaskRecord:
    id: str
    agentType: AgentType
    status: TaskStatus
    title: str
    originalUserRequest: str
    workerInstruction: str
    createdAt: int
    runInBackground: bool
    parentTaskId: str | None = None
    startedAt: int | None = None
    finishedAt: int | None = None
    model: str | None = None
    filesChanged: list[str] = field(default_factory=list)
    commandsExecuted: list[str] = field(default_factory=list)
    verificationNeeded: bool = False
    finalTextResponse: str | None = None
    summary: str | None = None
    error: str | None = None
    usage: TaskUsage | None = None
    evidence: list[str] = field(default_factory=list)
    unresolvedIssues: list[str] = field(default_factory=list)
    toolExecutions: list[ToolExecutionRecord] = field(default_factory=list)


@dataclass
class WorkerResult:
    taskId: str
    status: Literal["completed", "failed", "killed"]
    summary: str
    result: str
    filesChanged: list[str]
    commandsExecuted: list[str]
    evidence: list[str]
    unresolvedIssues: list[str]
    usage: TaskUsage | None = None


@dataclass
class CoordinatorTodo:
    id: str
    title: str
    description: str
    status: TodoStatus = "pending"
    priority: TodoPriority = "medium"
    dependencies: list[str] = field(default_factory=list)
    assignedTo: str = "main_agent"
    toolRequired: bool = False
    notes: str = ""
    result: str = ""
    blockingReason: str = ""
    evidence: list[str] = field(default_factory=list)
    retryCount: int = 0


@dataclass
class VerificationEvidence:
    command: str
    output: str
    result: Literal["PASS", "FAIL"]


@dataclass
class VerificationResult:
    taskId: str
    verdict: VerificationVerdict
    summary: str
    evidence: list[VerificationEvidence]
    missingRequirements: list[str]
    suspectedProblems: list[str]
    remediationTodos: list[CoordinatorTodo] = field(default_factory=list)


@dataclass
class CompletionDecision:
    done: bool
    reason: str
    nextAction: Literal["finalize", "retry-worker", "run-verification", "ask-user"] | None = None
