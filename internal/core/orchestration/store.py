from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from internal.core.orchestration.types import (
    CheckpointPayload,
    CheckpointRecord,
    FailureClass,
    RecoveryPolicy,
    StepArtifact,
    StepContract,
    StepRun,
    StepSpec,
    StepStatus,
    TaskGraphPlan,
    TaskKind,
    TaskRun,
)
from internal.services.config_db import DB_PATH


_RECOVERABLE_TO_READY: dict[str, str] = {
    "running": "ready",
    "verifying": "ready",
    "repairing": "ready",
}
_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"planning", "ready", "canceled"},
    "planning": {"ready", "failed", "canceled"},
    "ready": {"running", "verifying", "repairing", "waiting_dependency", "waiting_user", "completed", "failed", "canceled"},
    "running": {"completed", "failed", "waiting_user", "ready"},
    "waiting_dependency": {"ready", "verifying", "repairing", "canceled", "failed"},
    "waiting_user": {"ready", "canceled", "failed"},
    "verifying": {"completed", "failed", "waiting_user", "ready"},
    "repairing": {"completed", "failed", "waiting_user", "ready"},
    "completed": set(),
    "failed": {"ready"},
    "canceled": set(),
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _initial_step_status(step: StepSpec) -> StepStatus:
    return "ready" if not step.dependsOn else "waiting_dependency"


class OrchestrationStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path or DB_PATH).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # Persistent connection avoids per-operation open/close overhead.
        # check_same_thread=False is safe because _lock serialises all access.
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self.init_schema()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Acquire lock, yield the shared connection, commit or rollback."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # Keep _connect as an alias so any external callers aren't broken.
    _connect = _tx

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def init_schema(self) -> None:
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_task_runs (
                    task_run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_request TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_step_runs (
                    step_run_id TEXT PRIMARY KEY,
                    task_run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    executor TEXT NOT NULL,
                    inputs_json TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    verification_mode TEXT NOT NULL,
                    retry_policy_json TEXT NOT NULL,
                    recovery_point TEXT NOT NULL,
                    prompt_digest TEXT NOT NULL,
                    upstream_artifact_refs_json TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    evidence_summary TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    last_checkpoint_id TEXT,
                    failure_class TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    started_at INTEGER,
                    finished_at INTEGER,
                    UNIQUE(task_run_id, step_id),
                    FOREIGN KEY(task_run_id) REFERENCES orchestration_task_runs(task_run_id) ON DELETE CASCADE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_step_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    step_run_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(step_run_id) REFERENCES orchestration_step_runs(step_run_id) ON DELETE CASCADE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    step_run_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(step_run_id) REFERENCES orchestration_step_runs(step_run_id) ON DELETE CASCADE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_recovery_events (
                    recovery_event_id TEXT PRIMARY KEY,
                    task_run_id TEXT NOT NULL,
                    step_run_id TEXT,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(task_run_id) REFERENCES orchestration_task_runs(task_run_id) ON DELETE CASCADE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_lease_heartbeats (
                    step_run_id TEXT PRIMARY KEY,
                    lease_owner TEXT NOT NULL,
                    heartbeat_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY(step_run_id) REFERENCES orchestration_step_runs(step_run_id) ON DELETE CASCADE
                )
                """
            )
            # Indices for hot query paths (idempotent — IF NOT EXISTS).
            cur.execute("CREATE INDEX IF NOT EXISTS idx_step_runs_task_id ON orchestration_step_runs(task_run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_step_runs_status ON orchestration_step_runs(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_session_id ON orchestration_task_runs(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_step_id ON orchestration_step_artifacts(step_run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_step_id ON orchestration_checkpoints(step_run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_recovery_events_task_id ON orchestration_recovery_events(task_run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lease_expires ON orchestration_lease_heartbeats(expires_at)")

    def create_task_run(
        self,
        *,
        session_id: str,
        user_request: str,
        task_kind: TaskKind,
        plan: TaskGraphPlan,
    ) -> TaskRun:
        now = _now_ms()
        task_run_id = str(uuid.uuid4())
        plan_digest = _digest(
            {
                "taskKind": plan.taskKind,
                "steps": [self._serialize_step_spec(step) for step in plan.steps],
            }
        )
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_task_runs (
                    task_run_id, session_id, user_request, task_kind, status, plan_digest, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_run_id, session_id, user_request, task_kind, "ready", plan_digest, now, now),
            )
            for step in plan.steps:
                conn.execute(
                    """
                    INSERT INTO orchestration_step_runs (
                        step_run_id, task_run_id, step_id, kind, goal, status, depends_on_json, executor,
                        inputs_json, contract_json, verification_mode, retry_policy_json, recovery_point,
                        prompt_digest, upstream_artifact_refs_json, attempt_count, evidence_summary, summary,
                        last_checkpoint_id, failure_class, created_at, updated_at, started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        task_run_id,
                        step.stepId,
                        step.kind,
                        step.goal,
                        _initial_step_status(step),
                        json.dumps(step.dependsOn, ensure_ascii=True),
                        step.executor,
                        json.dumps(step.inputs, ensure_ascii=True),
                        json.dumps(self._serialize_contract(step.contract), ensure_ascii=True),
                        step.verificationMode,
                        json.dumps(self._serialize_recovery_policy(step.retryPolicy), ensure_ascii=True),
                        step.recoveryPoint,
                        _digest({"goal": step.goal, "inputs": step.inputs}),
                        json.dumps([], ensure_ascii=True),
                        0,
                        "",
                        "",
                        None,
                        None,
                        now,
                        now,
                        None,
                        None,
                    ),
                )
        return self.get_task_run(task_run_id)  # type: ignore[return-value]

    def get_task_run(self, task_run_id: str) -> TaskRun | None:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM orchestration_task_runs WHERE task_run_id = ?",
                (task_run_id,),
            ).fetchone()
        return self._row_to_task_run(row) if row else None

    def update_task_run_status(self, task_run_id: str, status: StepStatus) -> TaskRun:
        with self._tx() as conn:
            conn.execute(
                "UPDATE orchestration_task_runs SET status = ?, updated_at = ? WHERE task_run_id = ?",
                (status, _now_ms(), task_run_id),
            )
        return self.get_task_run(task_run_id)  # type: ignore[return-value]

    def list_steps(self, task_run_id: str) -> list[StepRun]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT * FROM orchestration_step_runs WHERE task_run_id = ? ORDER BY created_at, step_id",
                (task_run_id,),
            ).fetchall()
        return [self._row_to_step_run(row) for row in rows]

    def list_steps_by_session(self, session_id: str) -> list[StepRun]:
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT s.* FROM orchestration_step_runs s
                JOIN orchestration_task_runs t ON t.task_run_id = s.task_run_id
                WHERE t.session_id = ?
                ORDER BY s.created_at, s.step_id
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_step_run(row) for row in rows]

    def get_step_run(self, step_run_id: str) -> StepRun | None:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM orchestration_step_runs WHERE step_run_id = ?",
                (step_run_id,),
            ).fetchone()
        return self._row_to_step_run(row) if row else None

    def find_step_run(self, task_run_id: str, step_id: str) -> StepRun | None:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM orchestration_step_runs WHERE task_run_id = ? AND step_id = ?",
                (task_run_id, step_id),
            ).fetchone()
        return self._row_to_step_run(row) if row else None

    def transition_step(
        self,
        step_run_id: str,
        *,
        from_status: StepStatus,
        to_status: StepStatus,
        summary: str | None = None,
        failure_class: FailureClass | None = None,
        last_checkpoint_id: str | None = None,
    ) -> StepRun:
        step = self.get_step_run(step_run_id)
        if step is None:
            raise KeyError(step_run_id)
        if to_status not in _TRANSITIONS.get(from_status, set()):
            raise ValueError(f"Invalid transition {from_status} -> {to_status}")
        now = _now_ms()
        started_at = step.startedAt
        finished_at = step.finishedAt
        attempt_count = step.attemptCount
        if to_status in {"running", "verifying", "repairing"}:
            started_at = now
            attempt_count += 1
        if to_status in {"completed", "failed", "canceled"}:
            finished_at = now
        # Conditional UPDATE on (step_run_id, status) prevents TOCTOU between
        # the read above and this write — another writer that already moved the
        # step out of from_status will leave 0 rowcount and we'll raise.
        with self._tx() as conn:
            cur = conn.execute(
                """
                UPDATE orchestration_step_runs
                SET status = ?, summary = ?, failure_class = ?, last_checkpoint_id = ?,
                    updated_at = ?, started_at = ?, finished_at = ?, attempt_count = ?
                WHERE step_run_id = ? AND status = ?
                """,
                (
                    to_status,
                    summary if summary is not None else step.summary,
                    failure_class if failure_class is not None else step.failureClass,
                    last_checkpoint_id if last_checkpoint_id is not None else step.lastCheckpointId,
                    now,
                    started_at,
                    finished_at,
                    attempt_count,
                    step_run_id,
                    from_status,
                ),
            )
            if cur.rowcount == 0:
                current = conn.execute(
                    "SELECT status FROM orchestration_step_runs WHERE step_run_id = ?",
                    (step_run_id,),
                ).fetchone()
                actual = current["status"] if current else "<missing>"
                raise ValueError(
                    f"transition_step race: expected {from_status} but row is {actual}"
                )
        return self.get_step_run(step_run_id)  # type: ignore[return-value]

    def set_step_ready(self, step_run_id: str, *, summary: str = "") -> StepRun:
        with self._tx() as conn:
            conn.execute(
                """
                UPDATE orchestration_step_runs
                SET status = ?, summary = ?, failure_class = ?, updated_at = ?
                WHERE step_run_id = ?
                """,
                ("ready", summary, None, _now_ms(), step_run_id),
            )
        return self.get_step_run(step_run_id)  # type: ignore[return-value]

    def append_step_artifact(
        self,
        step_run_id: str,
        *,
        artifact_type: str,
        payload: dict[str, Any],
        summary: str,
        created_by: str,
    ) -> StepArtifact:
        artifact = StepArtifact(
            artifactId=str(uuid.uuid4()),
            stepRunId=step_run_id,
            artifactType=artifact_type,
            payload=payload,
            summary=summary,
            createdBy=created_by,
            createdAt=_now_ms(),
        )
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_step_artifacts (
                    artifact_id, step_run_id, artifact_type, payload_json, summary, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifactId,
                    artifact.stepRunId,
                    artifact.artifactType,
                    json.dumps(artifact.payload, ensure_ascii=True),
                    artifact.summary,
                    artifact.createdBy,
                    artifact.createdAt,
                ),
            )
            row = conn.execute(
                """
                SELECT upstream_artifact_refs_json, evidence_summary
                FROM orchestration_step_runs
                WHERE step_run_id = ?
                """,
                (step_run_id,),
            ).fetchone()
            refs = json.loads(row["upstream_artifact_refs_json"]) if row else []
            refs.append(artifact.artifactId)
            evidence_summary = "\n".join(filter(None, [row["evidence_summary"] if row else "", summary]))
            conn.execute(
                """
                UPDATE orchestration_step_runs
                SET upstream_artifact_refs_json = ?, evidence_summary = ?, updated_at = ?
                WHERE step_run_id = ?
                """,
                (json.dumps(refs, ensure_ascii=True), evidence_summary, _now_ms(), step_run_id),
            )
        return artifact

    def list_step_artifacts(self, step_run_id: str) -> list[StepArtifact]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT * FROM orchestration_step_artifacts WHERE step_run_id = ? ORDER BY created_at",
                (step_run_id,),
            ).fetchall()
        return [
            StepArtifact(
                artifactId=row["artifact_id"],
                stepRunId=row["step_run_id"],
                artifactType=row["artifact_type"],
                payload=json.loads(row["payload_json"]),
                summary=row["summary"],
                createdBy=row["created_by"],
                createdAt=row["created_at"],
            )
            for row in rows
        ]

    def commit_checkpoint(self, step_run_id: str, payload: CheckpointPayload) -> CheckpointRecord:
        checkpoint = CheckpointRecord(
            checkpointId=str(uuid.uuid4()),
            stepRunId=step_run_id,
            payload=payload,
            createdAt=_now_ms(),
        )
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_checkpoints (checkpoint_id, step_run_id, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    checkpoint.checkpointId,
                    checkpoint.stepRunId,
                    json.dumps(
                        {
                            "recoveryPoint": payload.recoveryPoint,
                            "summary": payload.summary,
                            "artifactRefs": payload.artifactRefs,
                            "data": payload.data,
                        },
                        ensure_ascii=True,
                    ),
                    checkpoint.createdAt,
                ),
            )
            conn.execute(
                """
                UPDATE orchestration_step_runs
                SET last_checkpoint_id = ?, updated_at = ?
                WHERE step_run_id = ?
                """,
                (checkpoint.checkpointId, _now_ms(), step_run_id),
            )
        return checkpoint

    def lease_step(self, step_run_id: str, *, lease_owner: str, lease_ttl_seconds: int = 30) -> bool:
        now = _now_ms()
        expires_at = now + lease_ttl_seconds * 1000
        # Single conditional upsert: succeed only if no row exists, or the existing
        # lease has expired, or the existing lease is owned by the same caller.
        with self._tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO orchestration_lease_heartbeats (step_run_id, lease_owner, heartbeat_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(step_run_id) DO UPDATE SET
                    lease_owner = excluded.lease_owner,
                    heartbeat_at = excluded.heartbeat_at,
                    expires_at = excluded.expires_at
                WHERE orchestration_lease_heartbeats.expires_at <= excluded.heartbeat_at
                   OR orchestration_lease_heartbeats.lease_owner = excluded.lease_owner
                """,
                (step_run_id, lease_owner, now, expires_at),
            )
            if cur.rowcount == 0:
                # Conflict and the WHERE clause rejected the update: another live owner.
                return False
        return True

    def release_step_lease(self, step_run_id: str, *, lease_owner: str | None = None) -> None:
        # Owner-scoped release: never delete another runtime's lease. If lease_owner
        # is None we keep the legacy behaviour (best-effort delete) for callers that
        # genuinely need to drop any holder (e.g. administrative cleanup).
        with self._tx() as conn:
            if lease_owner is None:
                conn.execute(
                    "DELETE FROM orchestration_lease_heartbeats WHERE step_run_id = ?",
                    (step_run_id,),
                )
            else:
                conn.execute(
                    "DELETE FROM orchestration_lease_heartbeats WHERE step_run_id = ? AND lease_owner = ?",
                    (step_run_id, lease_owner),
                )

    def refresh_waiting_dependencies(self, task_run_id: str) -> None:
        steps = {step.stepId: step for step in self.list_steps(task_run_id)}
        with self._tx() as conn:
            for step in steps.values():
                if step.status != "waiting_dependency":
                    continue
                dependencies = [steps.get(dep_id) for dep_id in step.dependsOn]
                if any(dep is None for dep in dependencies):
                    continue
                if all(dep.status == "completed" for dep in dependencies):
                    conn.execute(
                        """
                        UPDATE orchestration_step_runs
                        SET status = ?, updated_at = ?
                        WHERE step_run_id = ?
                        """,
                        ("ready", _now_ms(), step.stepRunId),
                    )

    def insert_step(self, *, task_run_id: str, step_spec: StepSpec, status: StepStatus = "ready") -> StepRun:
        now = _now_ms()
        step_run_id = str(uuid.uuid4())
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_step_runs (
                    step_run_id, task_run_id, step_id, kind, goal, status, depends_on_json, executor,
                    inputs_json, contract_json, verification_mode, retry_policy_json, recovery_point,
                    prompt_digest, upstream_artifact_refs_json, attempt_count, evidence_summary, summary,
                    last_checkpoint_id, failure_class, created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_run_id,
                    task_run_id,
                    step_spec.stepId,
                    step_spec.kind,
                    step_spec.goal,
                    status,
                    json.dumps(step_spec.dependsOn, ensure_ascii=True),
                    step_spec.executor,
                    json.dumps(step_spec.inputs, ensure_ascii=True),
                    json.dumps(self._serialize_contract(step_spec.contract), ensure_ascii=True),
                    step_spec.verificationMode,
                    json.dumps(self._serialize_recovery_policy(step_spec.retryPolicy), ensure_ascii=True),
                    step_spec.recoveryPoint,
                    _digest({"goal": step_spec.goal, "inputs": step_spec.inputs}),
                    json.dumps([], ensure_ascii=True),
                    0,
                    "",
                    "",
                    None,
                    None,
                    now,
                    now,
                    None,
                    None,
                ),
            )
        return self.get_step_run(step_run_id)  # type: ignore[return-value]

    def update_step_dependencies(self, step_run_id: str, depends_on: list[str], *, status: StepStatus | None = None) -> None:
        with self._tx() as conn:
            if status is None:
                conn.execute(
                    """
                    UPDATE orchestration_step_runs
                    SET depends_on_json = ?, updated_at = ?
                    WHERE step_run_id = ?
                    """,
                    (json.dumps(depends_on, ensure_ascii=True), _now_ms(), step_run_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE orchestration_step_runs
                    SET depends_on_json = ?, status = ?, updated_at = ?
                    WHERE step_run_id = ?
                    """,
                    (json.dumps(depends_on, ensure_ascii=True), status, _now_ms(), step_run_id),
                )

    def add_recovery_event(self, *, task_run_id: str, step_run_id: str | None, event_type: str, detail: str) -> None:
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_recovery_events (
                    recovery_event_id, task_run_id, step_run_id, event_type, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), task_run_id, step_run_id, event_type, detail, _now_ms()),
            )

    def resume_incomplete_runs(self) -> list[str]:
        recovered: list[str] = []
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT step_run_id, task_run_id, step_id, status
                FROM orchestration_step_runs
                WHERE status IN ('running', 'verifying', 'repairing')
                """
            ).fetchall()
            for row in rows:
                next_status = _RECOVERABLE_TO_READY[row["status"]]
                conn.execute(
                    """
                    UPDATE orchestration_step_runs
                    SET status = ?, summary = ?, failure_class = ?, updated_at = ?
                    WHERE step_run_id = ?
                    """,
                    (
                        next_status,
                        f"Recovered after crash from {row['status']}",
                        "system_crash",
                        _now_ms(),
                        row["step_run_id"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO orchestration_recovery_events (
                        recovery_event_id, task_run_id, step_run_id, event_type, detail, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        row["task_run_id"],
                        row["step_run_id"],
                        "resume",
                        f"Recovered step {row['step_id']} from {row['status']} to {next_status}",
                        _now_ms(),
                    ),
                )
                if row["task_run_id"] not in recovered:
                    recovered.append(row["task_run_id"])
        return recovered

    @staticmethod
    def _serialize_contract(contract: StepContract) -> dict[str, Any]:
        return {
            "doneWhen": contract.doneWhen,
            "mustProduce": contract.mustProduce,
            "mustNotChange": contract.mustNotChange,
            "requiredChecks": contract.requiredChecks,
            "evidenceShape": contract.evidenceShape,
            "repairHint": contract.repairHint,
        }

    @staticmethod
    def _deserialize_contract(payload: str) -> StepContract:
        return StepContract(**json.loads(payload))

    @staticmethod
    def _serialize_recovery_policy(policy: RecoveryPolicy) -> dict[str, Any]:
        return {
            "maxAttempts": policy.maxAttempts,
            "onTransient": policy.onTransient,
            "onDeterministic": policy.onDeterministic,
            "onDependency": policy.onDependency,
            "onUserDecision": policy.onUserDecision,
            "onSystemCrash": policy.onSystemCrash,
        }

    @staticmethod
    def _deserialize_recovery_policy(payload: str) -> RecoveryPolicy:
        return RecoveryPolicy(**json.loads(payload))

    def _serialize_step_spec(self, step: StepSpec) -> dict[str, Any]:
        return {
            "stepId": step.stepId,
            "kind": step.kind,
            "goal": step.goal,
            "dependsOn": step.dependsOn,
            "executor": step.executor,
            "inputs": step.inputs,
            "contract": self._serialize_contract(step.contract),
            "verificationMode": step.verificationMode,
            "retryPolicy": self._serialize_recovery_policy(step.retryPolicy),
            "recoveryPoint": step.recoveryPoint,
        }

    @staticmethod
    def _row_to_task_run(row: sqlite3.Row) -> TaskRun:
        return TaskRun(
            taskRunId=row["task_run_id"],
            sessionId=row["session_id"],
            userRequest=row["user_request"],
            taskKind=row["task_kind"],
            status=row["status"],
            planDigest=row["plan_digest"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    def _row_to_step_run(self, row: sqlite3.Row) -> StepRun:
        return StepRun(
            stepRunId=row["step_run_id"],
            taskRunId=row["task_run_id"],
            stepId=row["step_id"],
            kind=row["kind"],
            goal=row["goal"],
            status=row["status"],
            dependsOn=json.loads(row["depends_on_json"]),
            executor=row["executor"],
            inputs=json.loads(row["inputs_json"]),
            contract=self._deserialize_contract(row["contract_json"]),
            verificationMode=row["verification_mode"],
            retryPolicy=self._deserialize_recovery_policy(row["retry_policy_json"]),
            recoveryPoint=row["recovery_point"],
            promptDigest=row["prompt_digest"],
            upstreamArtifactRefs=json.loads(row["upstream_artifact_refs_json"]),
            attemptCount=row["attempt_count"],
            evidenceSummary=row["evidence_summary"],
            summary=row["summary"],
            lastCheckpointId=row["last_checkpoint_id"],
            failureClass=row["failure_class"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
        )
