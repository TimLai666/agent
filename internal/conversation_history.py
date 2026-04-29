from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse


MessageHistory = list[ModelRequest | ModelResponse]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_session_id(session_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "").strip())
    return cleaned or "session"


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
        self._meta_path(session_id).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
            self._messages_path(session_id).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _read_meta(self, session_id: str) -> dict[str, Any]:
        path = self._meta_path(session_id)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
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
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
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
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(ModelMessagesTypeAdapter.validate_python(payload))

    def delete_session(self, session_id: str) -> bool:
        path = self._session_dir(session_id)
        if not path.exists():
            return False
        shutil.rmtree(path)
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
