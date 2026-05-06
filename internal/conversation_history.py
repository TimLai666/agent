from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse


MessageHistory = list[ModelRequest | ModelResponse]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically: write to a sibling temp file, then os.replace."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _safe_session_id(session_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "").strip())
    # Reject path-traversal components (e.g. ".", "..") that the regex would
    # otherwise leave untouched because dots are allowed.
    if not cleaned or cleaned.strip(".") == "":
        return "session"
    return cleaned


@dataclass(frozen=True)
class ConversationSession:
    session_id: str
    created_at: str
    updated_at: str
    turn_count: int
    preview: str
    path: Path


class ConversationHistoryStore:
    """Persist raw conversation turns and resumable model history per session."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        from internal.paths import TIM_AGENT_CONVERSATIONS_DIR

        base = Path(root_dir).expanduser().resolve() if root_dir is not None else TIM_AGENT_CONVERSATIONS_DIR
        self.root_dir = base
        # Per-session metadata cache; invalidated on write.
        self._meta_cache: dict[str, dict[str, Any]] = {}

    def _session_dir(self, session_id: str) -> Path:
        return self.root_dir / _safe_session_id(session_id)

    def _meta_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "metadata.json"

    def _turns_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "turns.jsonl"

    def _messages_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "messages.json"

    def append_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
        messages: MessageHistory | None = None,
        timestamp: str | None = None,
    ) -> None:
        ts = timestamp or _utc_now()
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        meta = self._read_meta(session_id)
        turn_count = int(meta.get("turn_count") or 0) + 1
        created_at = str(meta.get("created_at") or ts)
        preview = (user_text or assistant_text or "").strip().replace("\n", " ")[:160]
        meta.update(
            {
                "session_id": session_id,
                "created_at": created_at,
                "updated_at": ts,
                "turn_count": turn_count,
                "preview": preview or str(meta.get("preview") or ""),
            }
        )
        _atomic_write_text(
            self._meta_path(session_id),
            json.dumps(meta, ensure_ascii=False, indent=2),
        )
        self._meta_cache[session_id] = meta

        turn = {
            "session_id": session_id,
            "timestamp": ts,
            "user": user_text,
            "assistant": assistant_text,
        }
        with self._turns_path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(turn, ensure_ascii=False) + "\n")

        if messages is not None:
            payload = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
            _atomic_write_text(
                self._messages_path(session_id),
                json.dumps(payload, ensure_ascii=False, indent=2),
            )

    def _read_meta(self, session_id: str) -> dict[str, Any]:
        if session_id in self._meta_cache:
            return self._meta_cache[session_id]
        path = self._meta_path(session_id)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result = data if isinstance(data, dict) else {}
            self._meta_cache[session_id] = result
            return result
        except Exception:
            return {}

    def list_sessions(self) -> list[ConversationSession]:
        if not self.root_dir.exists():
            return []
        sessions: list[ConversationSession] = []
        for child in self.root_dir.iterdir():
            if not child.is_dir():
                continue
            meta_path = child / "metadata.json"
            if not meta_path.exists():
                continue
            sid = child.name
            if sid in self._meta_cache:
                meta = self._meta_cache[sid]
            else:
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if isinstance(meta, dict):
                        self._meta_cache[sid] = meta
                except Exception:
                    continue
            sessions.append(
                ConversationSession(
                    session_id=str(meta.get("session_id") or child.name),
                    created_at=str(meta.get("created_at") or ""),
                    updated_at=str(meta.get("updated_at") or ""),
                    turn_count=int(meta.get("turn_count") or 0),
                    preview=str(meta.get("preview") or ""),
                    path=child,
                )
            )
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def load_display_history(self, session_id: str) -> list[tuple[str, str]]:
        path = self._turns_path(session_id)
        if not path.exists():
            return []
        pairs: list[tuple[str, str]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            pairs.append((str(item.get("user") or ""), str(item.get("assistant") or "")))
        return pairs

    def load_message_history(self, session_id: str) -> MessageHistory:
        path = self._messages_path(session_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return list(ModelMessagesTypeAdapter.validate_python(payload))
        except Exception:
            # Corrupted or partially-written history — degrade gracefully.
            return []

    def delete_session(self, session_id: str) -> bool:
        path = self._session_dir(session_id)
        if not path.exists():
            return False
        self._meta_cache.pop(session_id, None)
        try:
            shutil.rmtree(path)
        except OSError:
            # On Windows, files held by another handle prevent removal.
            # Best-effort cleanup: leave whatever survived in place.
            return False
        return True

    def search(
        self,
        query: str,
        *,
        scope: str = "all",
        session_id: str | None = None,
        current_session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, str]]:
        needle = (query or "").strip().lower()
        if not needle:
            return []
        scope = (scope or "all").strip().lower()
        if scope == "current":
            candidate_ids = [current_session_id] if current_session_id else []
        elif scope == "session":
            candidate_ids = [session_id] if session_id else []
        else:
            candidate_ids = [item.session_id for item in self.list_sessions()]

        results: list[dict[str, str]] = []
        for candidate in candidate_ids:
            if not candidate:
                continue
            path = self._turns_path(candidate)
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if len(results) >= limit:
                    return results
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                haystack = f"{item.get('user') or ''}\n{item.get('assistant') or ''}"
                if needle not in haystack.lower():
                    continue
                snippet = haystack.replace("\n", " ").strip()
                results.append(
                    {
                        "session_id": str(candidate),
                        "timestamp": str(item.get("timestamp") or ""),
                        "snippet": snippet[:500],
                    }
                )
        return results
