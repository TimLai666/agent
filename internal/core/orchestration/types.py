from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


TaskKind = Literal["question", "research", "implementation", "bugfix", "infra"]
StepKind = Literal["discover", "plan", "implement", "verify", "repair", "synthesize", "ask_user"]
StepStatus = Literal[
    "queued",
    "planning",
    "ready",
    "running",
    "waiting_dependency",
    "waiting_user",
    "verifying",
    "repairing",
    "completed",
    "failed",
    "canceled",
]
VerificationVerdict = Literal["PASS", "FAIL", "PARTIAL", "BLOCKED"]
FailureClass = Literal["transient", "deterministic", "dependency", "user_decision", "system_crash"]


@dataclass
class StepContract:
    doneWhen: str
    mustProduce: list[str] = field(default_factory=list)
    mustNotChange: list[str] = field(default_factory=list)
    requiredChecks: list[str] = field(default_factory=list)
    evidenceShape: list[str] = field(default_factory=list)
    repairHint: str = ""


@dataclass
class RecoveryPolicy:
    maxAttempts: int = 2
    onTransient: str = "retry-step"
    onDeterministic: str = "create-repair-step"
    onDependency: str = "wait-dependency"
    onUserDecision: str = "wait-user"
    onSystemCrash: str = "resume-from-checkpoint"


@dataclass
class CheckpointPayload:
    recoveryPoint: str
    summary: str
    artifactRefs: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepSpec:
    stepId: str
    kind: StepKind
    goal: str
    executor: str
    inputs: dict[str, Any]
    contract: StepContract
    verificationMode: str
    retryPolicy: RecoveryPolicy
    recoveryPoint: str
    dependsOn: list[str] = field(default_factory=list)


@dataclass
class TaskGraphPlan:
    taskKind: TaskKind
    steps: list[StepSpec] = field(default_factory=list)


@dataclass
class VerificationEvidenceItem:
    name: str
    result: Literal["PASS", "FAIL"]
    detail: str


@dataclass
class VerificationReport:
    verdict: VerificationVerdict
    summary: str
    checkedItems: list[str]
    failedItems: list[str]
    evidence: list[VerificationEvidenceItem]
    remediationSteps: list[StepSpec] = field(default_factory=list)
    confidence: float = 0.0
    requiresUserInput: bool = False


@dataclass
class StepExecutionResult:
    status: Literal["completed", "failed", "waiting_user"] = "completed"
    summary: str = ""
    result: str = ""
    filesChanged: list[str] = field(default_factory=list)
    commandsExecuted: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    unresolvedIssues: list[str] = field(default_factory=list)
    recoverySummary: str = ""
    failureClass: FailureClass | None = None
    requiresUserInput: bool = False


@dataclass
class TaskRun:
    taskRunId: str
    sessionId: str
    userRequest: str
    taskKind: TaskKind
    status: StepStatus
    planDigest: str
    createdAt: int
    updatedAt: int


@dataclass
class StepRun:
    stepRunId: str
    taskRunId: str
    stepId: str
    kind: StepKind
    goal: str
    status: StepStatus
    dependsOn: list[str]
    executor: str
    inputs: dict[str, Any]
    contract: StepContract
    verificationMode: str
    retryPolicy: RecoveryPolicy
    recoveryPoint: str
    promptDigest: str
    upstreamArtifactRefs: list[str]
    attemptCount: int
    evidenceSummary: str
    summary: str
    lastCheckpointId: str | None
    failureClass: FailureClass | None
    createdAt: int
    updatedAt: int
    startedAt: int | None = None
    finishedAt: int | None = None


@dataclass
class StepArtifact:
    artifactId: str
    stepRunId: str
    artifactType: str
    payload: dict[str, Any]
    summary: str
    createdBy: str
    createdAt: int


@dataclass
class CheckpointRecord:
    checkpointId: str
    stepRunId: str
    payload: CheckpointPayload
    createdAt: int
