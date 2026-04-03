from __future__ import annotations

import re
from pathlib import Path

_MD_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")


def _is_remote_or_data(target: str) -> bool:
    lowered = target.lower()
    return (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("data:")
    )


def _normalize_target(target: str, base_dir: Path) -> str:
    cleaned = target.strip()
    if not cleaned:
        return cleaned

    # Keep optional width/title suffix intact: "path =300" or "path \"title\"".
    parts = cleaned.split(maxsplit=1)
    raw_path = parts[0].strip().strip("<>").strip('"\'')
    suffix = f" {parts[1]}" if len(parts) > 1 else ""

    if _is_remote_or_data(raw_path):
        return cleaned

    path_obj = Path(raw_path).expanduser()
    if not path_obj.is_absolute():
        path_obj = (base_dir / path_obj).resolve()
    else:
        path_obj = path_obj.resolve()

    return f"{path_obj.as_posix()}{suffix}"


def enforce_absolute_image_paths(text: str, base_dir: Path | None = None) -> str:
    if not text:
        return text
    # 使用沙盒目錄作為 agent 的工作目錄，不暴露真實 CWD
    from internal.paths import TIM_AGENT_SANDBOX_DIR
    root = (base_dir or TIM_AGENT_SANDBOX_DIR).resolve()

    def _replace(match: re.Match[str]) -> str:
        alt = match.group("alt")
        target = match.group("target")
        normalized = _normalize_target(target, root)
        return f"![{alt}]({normalized})"

    return _MD_IMAGE_RE.sub(_replace, text)


class ImagePathStreamNormalizer:
    def __init__(self, base_dir: Path | None = None, keep_tail: int = 512) -> None:
        self._base_dir = base_dir
        self._keep_tail = keep_tail
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buffer += chunk
        if len(self._buffer) <= self._keep_tail:
            return ""

        emit = self._buffer[:-self._keep_tail]
        self._buffer = self._buffer[-self._keep_tail :]
        return enforce_absolute_image_paths(emit, self._base_dir)

    def flush(self) -> str:
        if not self._buffer:
            return ""
        final = enforce_absolute_image_paths(self._buffer, self._base_dir)
        self._buffer = ""
        return final
