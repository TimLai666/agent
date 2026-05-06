"""
免費網路搜索工具 - 使用 DuckDuckGo（無需 API key）

提供類似 Anthropic WebSearch 的功能，但完全免費且無需註冊。
"""

import asyncio
import random
from typing import Callable, Any

from internal.logger import logger

from pydantic_ai import Agent

try:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException
    _DDGS_AVAILABLE = True
except Exception as _ddgs_import_err:  # pragma: no cover - optional dependency
    DDGS = None  # type: ignore[assignment]
    DDGSException = Exception  # type: ignore[assignment, misc]
    _DDGS_AVAILABLE = False
    logger.warning("ddgs not available; web search tools will be disabled: %s", _ddgs_import_err)

safe_search_default = "off"

# 超時與重試設定（秒、次數，可調）
DEFAULT_BACKEND_TIMEOUT = 10  # seconds per backend search
DEFAULT_BACKEND_RETRIES = 1   # number of retries on failure (0 = no retry)
BACKOFF_BASE_SECONDS = 1      # base backoff for retries (exponential backoff)

# 可配置的後端清單（按搜尋類型）
AVAILABLE_BACKENDS_TEXT = [
    "bing",
    "brave",
    "duckduckgo",
    "google",
    "grokipedia",
    "mojeek",
    "yandex",
    "yahoo",
    "wikipedia",
]
# 對新聞搜尋，我們使用支持新聞來源的後端（可依需求調整）
AVAILABLE_BACKENDS_NEWS = ["duckduckgo", "bing", "yahoo"]
# 對圖片搜尋，使用支持圖片結果的後端
AVAILABLE_BACKENDS_IMAGES = ["duckduckgo"]


def _is_no_results_error(err: Exception) -> bool:
    """判斷是否屬於 DDGS 的「無結果」情境。"""
    if isinstance(err, DDGSException):
        return "no results found" in str(err).lower()
    return False


def _is_transient_backend_error(err: Exception) -> bool:
    """判斷是否屬於後端暫時性網路錯誤（可重試/可降級）。"""
    text = str(err).lower()
    markers = [
        "sendrequest",
        "connection error",
        "broken pipe",
        "stream closed",
        "timed out",
        "timeout",
        "network",
    ]
    return any(marker in text for marker in markers)


def add_web_search_tools(agent: Agent) -> None:
    """
    註冊免費的網路搜索工具到 agent

    提供三個工具：
    - web_search: 一般網路搜索（使用 DuckDuckGo）
    - web_search_news: 新聞搜索（使用 DuckDuckGo News）
    - web_search_images: 圖片搜索（使用 DuckDuckGo Images）
    """
    if not _DDGS_AVAILABLE:
        logger.info("Skipping web_search tool registration (ddgs not available).")
        return
    agent.tool_plain(web_search)
    agent.tool_plain(web_search_news)
    agent.tool_plain(web_search_images)


async def _run_backend_callable(
    backend: str,
    sync_callable: Callable[[], list],
    timeout: int = DEFAULT_BACKEND_TIMEOUT,
    retries: int = DEFAULT_BACKEND_RETRIES,
    backoff_base: int = BACKOFF_BASE_SECONDS,
    jitter: bool = False,
) -> dict:
    """Run a blocking sync_callable in an executor with timeout, retries and exponential backoff.

    Returns a dict with 'backend' and either 'results' (list) or 'error' (str).
    """
    last_err = None
    loop = asyncio.get_running_loop()
    for attempt in range(retries + 1):
        try:
            logger.info(f"Performing {backend} search (attempt {attempt})")
            coro = loop.run_in_executor(None, sync_callable)
            results = await asyncio.wait_for(coro, timeout=timeout)
            return {"backend": backend, "results": results}
        except asyncio.TimeoutError as e:
            last_err = f"Timeout after {timeout}s"
            logger.warning(f"Timeout for {backend} (attempt {attempt}): {str(e)}")
        except Exception as e:
            if _is_no_results_error(e):
                logger.info(f"{backend} returned no results (attempt {attempt})")
                return {"backend": backend, "results": []}
            last_err = str(e)
            if _is_transient_backend_error(e):
                logger.warning(
                    f"後端 {backend} 暫時性錯誤（attempt {attempt}）: {last_err}"
                )
            else:
                logger.error(f"後端 {backend} 搜索時發生錯誤: {last_err}")

        # 重試前等待（指數回退，選擇性 jitter）
        if attempt < retries:
            backoff = backoff_base * (2 ** attempt)
            if jitter:
                backoff = backoff * (0.5 + random.random())
            await asyncio.sleep(backoff)

    return {"backend": backend, "error": last_err or "Unknown error"}

# --- 共用的格式化與合併 helper ---
def _format_backend_results(results: list, backend: str, all_results: list, kind: str = "text") -> list:
    """Generic formatter for backend results.

    kind: 'text' | 'news' | 'image'
    """
    if kind == "text":
        title_field, url_field, include_body = "title", "href", True
    elif kind == "news":
        title_field, url_field, include_body = "title", "url", True
    elif kind == "image":
        title_field, url_field, include_body = "title", "image", False
    else:
        title_field, url_field, include_body = "title", "href", True

    header_map = {"text": "找到 {n} 個結果：", "news": "找到 {n} 個新聞：", "image": "找到 {n} 張圖片："}
    header = header_map.get(kind, header_map["text"]).format(n=len(results))
    block = [f"## 後端：{backend} - {header}\n"]

    for idx, result in enumerate(results, 1):
        title = result.get(title_field, "無標題")
        url = result.get(url_field, "")
        body = result.get("body", "") if include_body else ""

        if not url:
            url = f"_no_{url_field}_{hash(title + (body or ''))}"

        block.append(f"{idx}. {title}")
        block.append(f"   URL: {url}")

        if kind == "news":
            source = result.get("source", "")
            date = result.get("date", "")
            if source:
                block.append(f"   來源: {source}")
            if date:
                block.append(f"   日期: {date}")

        if include_body and body:
            snippet = body[:200] + "..." if len(body) > 200 else body
            block.append(f"   摘要: {snippet}")

        block.append("")

        # append a normalized entry for de-dup
        entry = {"backend": backend, "title": title, "url": url}
        if include_body:
            entry["body"] = body
        if kind == "news":
            entry["date"] = result.get("date", "")
            entry["source"] = result.get("source", "")
        all_results.append(entry)

    return block


def _build_combined_block(all_results: list, header: str, include_body: bool = True) -> tuple:
    seen_urls = set()
    combined_block = [f"## {header}：\n"]
    combined_count = 0
    for entry in all_results:
        url = entry.get("url")
        title = entry.get("title")
        body = entry.get("body", "")

        if url in seen_urls:
            continue
        seen_urls.add(url)
        combined_count += 1
        combined_block.append(f"{combined_count}. {title}")
        combined_block.append(f"   URL: {url}")
        if include_body and body:
            snippet = body[:200] + "..." if len(body) > 200 else body
            combined_block.append(f"   摘要: {snippet}")
        combined_block.append("")

    return combined_block, combined_count


async def web_search(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
) -> str:
    """
    使用多個後端（例如 DuckDuckGo、Bing 等）進行網路搜索，呈現每個後端的原始結果，同時提供一個合併後（去重）的結果區塊。

    Args:
        query: 搜索查詢字串
        max_results: 每個後端最多返回結果數量（默認 5）
        region: 地區代碼（默認 wt-wt 為全球，zh-tw 為台灣，zh-cn 為中國）

    Returns:
        格式化的搜尋結果字串：先列出各後端的完整（不去重）結果，最後列出一個「全部結果（已去重）」區塊。
    """

    available_backends = AVAILABLE_BACKENDS_TEXT

    per_backend_formatted: list[str] = []
    all_results: list[dict] = []  # 用於最後做全局去重：元素 = {"backend":..., "title":..., "url":..., "body":...}
    backend_errors: list[str] = []


    # 非同步並行查詢所有後端（使用共用 helper）
    async def _search_backend(backend: str) -> dict:
        def _call():
            with DDGS() as ddgs:
                return list(ddgs.text(
                    query=query,
                    region=region,
                    max_results=max_results,
                    backend=backend,
                    safesearch=safe_search_default,
                ))
        return await _run_backend_callable(backend, _call) 

    tasks = [asyncio.create_task(_search_backend(b)) for b in available_backends]
    completed = await asyncio.gather(*tasks)

    # 依原始後端順序處理結果
    for res in completed:
        backend = res.get("backend") or "unknown"
        if res.get("error"):
            backend_errors.append(f"後端 {backend} 搜索時發生錯誤: {res.get('error')}")
            continue

        results = res.get("results") or []
        if not results:
            logger.info(f"No results from backend: {backend}")
            continue

        # 使用共用 formatter（不去重，保留後端原始順序）
        backend_block = _format_backend_results(results, backend, all_results, kind="text")
        per_backend_formatted.extend(backend_block)

        logger.info(f"{backend} search completed: {len(results)} results")

    if not all_results:
        combined_error = "\n".join(backend_errors) if backend_errors else None
        if combined_error:
            return f"未找到關於「{query}」的搜索結果。\n另外，發現以下後端錯誤：\n{combined_error}"
        return f"未找到關於「{query}」的搜索結果。"

    # 建立全域去重的「全部結果」區塊（使用共用 helper）
    combined_block, combined_count = _build_combined_block(all_results, "全部結果（已去重）", include_body=True)

    # 組合最終輸出：先 per-backend，再 combined
    result_lines = [f"## 搜索查詢：{query}\n"]
    result_lines.extend(per_backend_formatted)
    result_lines.append(f"## 合併後共找到 {combined_count} 個唯一結果（已去重）：\n")
    result_lines.extend(combined_block)

    if backend_errors:
        result_lines.append("\n## ⚠️ 以下後端返回錯誤：")
        result_lines.extend(backend_errors)

    used_backends = ", ".join(available_backends)
    result_lines.append(f"\n💡 提示：以上結果來自多個後端：{used_backends}")

    result_text = "\n".join(result_lines)

    return result_text


async def web_search_news(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
) -> str:
    """
    使用多個後端並行搜尋新聞，輸出每個後端的完整結果（不去重），以及一個「全部新聞（已去重）」合併區塊。
    """

    available_backends = AVAILABLE_BACKENDS_NEWS
    per_backend_formatted: list[str] = []
    all_results: list[dict] = []
    backend_errors: list[str] = []


    async def _search_backend(backend: str) -> dict:
        def _call():
            with DDGS() as ddgs:
                return list(ddgs.news(
                    query=query,
                    region=region,
                    max_results=max_results,
                    backend=backend,
                    safesearch=safe_search_default,
                ))
        return await _run_backend_callable(backend, _call) 

    tasks = [asyncio.create_task(_search_backend(b)) for b in available_backends]
    completed = await asyncio.gather(*tasks)

    for res in completed:
        backend = res.get("backend") or "unknown"
        if res.get("error"):
            backend_errors.append(f"後端 {backend} 搜索時發生錯誤: {res.get('error')}")
            continue

        results = res.get("results") or []
        if not results:
            logger.info(f"No results from backend: {backend}")
            continue

        # 使用共用 formatter（不去重，保留後端原始順序）
        backend_block = _format_backend_results(results, backend, all_results, kind="news")
        per_backend_formatted.extend(backend_block)

        logger.info(f"{backend} news search completed: {len(results)} results")

    if not all_results:
        combined_error = "\n".join(backend_errors) if backend_errors else None
        if combined_error:
            return f"未找到關於「{query}」的新聞。\n另外，發現以下後端錯誤：\n{combined_error}"
        return f"未找到關於「{query}」的新聞。"

    # 建立全域去重的「全部新聞結果」區塊（使用共用 helper）
    combined_block, combined_count = _build_combined_block(all_results, "全部新聞結果（已去重）", include_body=True)

    # 組合最終輸出：先 per-backend，再 combined
    result_lines = [f"## 新聞搜索：{query}\n"]
    result_lines.extend(per_backend_formatted)
    result_lines.append(f"## 合併後共找到 {combined_count} 個唯一新聞（已去重）：\n")
    result_lines.extend(combined_block)

    if backend_errors:
        result_lines.append("\n## ⚠️ 以下後端返回錯誤：")
        result_lines.extend(backend_errors)

    used_backends = ", ".join(available_backends)
    result_lines.append(f"\n💡 提示：以上新聞結果來自多個後端：{used_backends}")

    result_text = "\n".join(result_lines)

    return result_text

async def web_search_images(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
) -> str:
    """
    使用多個後端並行搜尋圖片，輸出每個後端的完整結果（不去重），以及一個「全部圖片（已去重）」合併區塊。
    """

    available_backends = AVAILABLE_BACKENDS_IMAGES
    per_backend_formatted: list[str] = []
    all_results: list[dict] = []
    backend_errors: list[str] = []


    async def _search_backend(backend: str) -> dict:
        def _call():
            with DDGS() as ddgs:
                return list(ddgs.images(
                    query=query,
                    region=region,
                    max_results=max_results,
                    backend=backend,
                    safesearch=safe_search_default,
                ))
        return await _run_backend_callable(backend, _call) 

    tasks = [asyncio.create_task(_search_backend(b)) for b in available_backends]
    completed = await asyncio.gather(*tasks)

    for res in completed:
        backend = res.get("backend") or "unknown"
        if res.get("error"):
            backend_errors.append(f"後端 {backend} 搜索時發生錯誤: {res.get('error')}")
            continue

        results = res.get("results") or []
        if not results:
            logger.info(f"No results from backend: {backend}")
            continue

        # 使用共用 formatter（不去重，保留後端原始順序）
        backend_block = _format_backend_results(results, backend, all_results, kind="image")
        per_backend_formatted.extend(backend_block)

        logger.info(f"{backend} image search completed: {len(results)} results")

    if not all_results:
        combined_error = "\n".join(backend_errors) if backend_errors else None
        if combined_error:
            return f"未找到關於「{query}」的圖片。\n另外，發現以下後端錯誤：\n{combined_error}"
        return f"未找到關於「{query}」的圖片。"

    # 建立全域去重的「全部圖片結果」區塊（使用共用 helper）
    combined_block, combined_count = _build_combined_block(all_results, "全部圖片結果（已去重）", include_body=False)

    # 組合最終輸出：先 per-backend，再 combined
    result_lines = [f"## 圖片搜索：{query}\n"]
    result_lines.extend(per_backend_formatted)
    result_lines.append(f"## 合併後共找到 {combined_count} 個唯一圖片（已去重）：\n")
    result_lines.extend(combined_block)

    if backend_errors:
        result_lines.append("\n## ⚠️ 以下後端返回錯誤：")
        result_lines.extend(backend_errors)

    used_backends = ", ".join(available_backends)
    result_lines.append(f"\n💡 提示：以上圖片結果來自多個後端：{used_backends}")

    result_text = "\n".join(result_lines)

    return result_text
