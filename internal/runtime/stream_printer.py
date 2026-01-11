import asyncio
from collections import deque
from typing import AsyncIterable

# 可配置參數：基礎每字延遲（seconds）、backlog 尺度、最小因子
BASE_DELAY = 0.1
BACKLOG_SCALE = 20.0
MIN_FACTOR = 0.1


async def stream_print(
    chunks: AsyncIterable[str],
    *,
    base_delay: float | None = None,
    backlog_scale: float | None = None,
    min_factor: float | None = None,
) -> None:
    """Consume an async iterable of text chunks and print them char-by-char.

    Delay per char is computed dynamically using the total backlog length (未印出字數).
    """
    if base_delay is None:
        base_delay = BASE_DELAY
    if backlog_scale is None:
        backlog_scale = BACKLOG_SCALE
    if min_factor is None:
        min_factor = MIN_FACTOR

    pending = deque()
    buffer = ""
    mode = "normal"
    tags = (
        "<tool-execution>",
        "</tool-execution>",
        "<discussion>",
        "</discussion>",
    )
    tag_labels = {
        "<tool-execution>": "\n---- TOOL EXECUTION ----\n",
        "</tool-execution>": "\n---- END TOOL EXECUTION ----\n",
        "<discussion>": "\n---- DISCUSSION ----\n",
        "</discussion>": "\n---- END DISCUSSION ----\n",
    }
    max_tag_len = max(len(tag) for tag in tags)

    def next_tag(text: str) -> tuple[int, str] | None:
        earliest_idx = -1
        earliest_tag = ""
        for tag in tags:
            idx = text.find(tag)
            if idx == -1:
                continue
            if earliest_idx == -1 or idx < earliest_idx:
                earliest_idx = idx
                earliest_tag = tag
        if earliest_idx == -1:
            return None
        return earliest_idx, earliest_tag
    async for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk
        while buffer:
            found = next_tag(buffer)
            if not found:
                if len(buffer) > max_tag_len - 1:
                    emit = buffer[: -(max_tag_len - 1)]
                    buffer = buffer[-(max_tag_len - 1) :]
                else:
                    emit = ""
                if emit:
                    if mode == "normal":
                        pending.append(emit)
                    else:
                        print(emit, end="", flush=True)
                if not emit:
                    break
                continue
            idx, tag = found
            if idx > 0:
                prefix = buffer[:idx]
                if mode == "normal":
                    pending.append(prefix)
                else:
                    print(prefix, end="", flush=True)
            print(tag_labels.get(tag, tag), end="", flush=True)
            if tag in ("<tool-execution>", "<discussion>"):
                mode = "fast"
            elif tag in ("</tool-execution>", "</discussion>"):
                mode = "normal"
            buffer = buffer[idx + len(tag):]

        while pending:
            backlog_len = sum(len(s) for s in pending)
            left = pending[0]
            ch, rest = left[0], left[1:]
            if rest:
                pending[0] = rest
            else:
                pending.popleft()

            print(ch, end="", flush=True)

            speed_factor = 1.0 / (1.0 + (backlog_len / backlog_scale))
            delay = max(base_delay * min_factor, base_delay * speed_factor)
            await asyncio.sleep(delay)

    while pending:
        backlog_len = sum(len(s) for s in pending)
        left = pending[0]
        ch, rest = left[0], left[1:]
        if rest:
            pending[0] = rest
        else:
            pending.popleft()
        print(ch, end="", flush=True)
        speed_factor = 1.0 / (1.0 + (backlog_len / backlog_scale))
        delay = max(base_delay * min_factor, base_delay * speed_factor)
        await asyncio.sleep(delay)

    # flush newline after complete
    print()
