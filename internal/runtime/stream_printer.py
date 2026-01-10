import asyncio
from collections import deque
from typing import AsyncIterable

# 可配置參數：基礎每字延遲（seconds）、backlog 尺度、最小因子
BASE_DELAY = 0.1
BACKLOG_SCALE = 20.0
MIN_FACTOR = 0.1


async def stream_print(chunks: AsyncIterable[str], *, base_delay: float | None = None, backlog_scale: float | None = None, min_factor: float | None = None) -> None:
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
    async for chunk in chunks:
        if not chunk:
            continue
        pending.append(chunk)

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
