"""
免費網路搜索工具 - 使用 DuckDuckGo（無需 API key）

提供類似 Anthropic WebSearch 的功能，但完全免費且無需註冊。
"""

import asyncio
from ddgs import DDGS
from internal.logger import logger

from pydantic_ai import Agent

safe_search_default = "off"


def add_web_search_tools(agent: Agent) -> None:
    """
    註冊免費的網路搜索工具到 agent

    提供三個工具：
    - web_search: 一般網路搜索（使用 DuckDuckGo）
    - web_search_news: 新聞搜索（使用 DuckDuckGo News）
    - web_search_images: 圖片搜索（使用 DuckDuckGo Images）
    """
    agent.tool_plain(web_search)
    agent.tool_plain(web_search_news)
    agent.tool_plain(web_search_images)


async def web_search(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
) -> str:
    """
    使用 DuckDuckGo 進行網路搜索（完全免費，無需 API key）

    Args:
        query: 搜索查詢字串
        max_results: 最多返回結果數量（默認 5）
        region: 地區代碼（默認 wt-wt 為全球，zh-tw 為台灣，zh-cn 為中國）

    Returns:
        格式化的搜索結果，包含標題、URL 和摘要
    """
    try:
        logger.info(f"Performing DuckDuckGo search: {query}")

        # DuckDuckGo 是同步 API，在 executor 中運行避免阻塞
        def _search():
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    query=query,
                    region=region,
                    max_results=max_results,
                    backend="auto",
                    safesearch=safe_search_default,
                ))
            return results

        # 在線程池中運行同步搜索
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _search)

        if not results:
            return f"未找到關於「{query}」的搜索結果。"

        # 格式化結果
        formatted_results = []
        formatted_results.append(f"搜索查詢：{query}\n")
        formatted_results.append(f"找到 {len(results)} 個結果：\n")

        for idx, result in enumerate(results, 1):
            title = result.get("title", "無標題")
            url = result.get("href", "")
            body = result.get("body", "")

            formatted_results.append(f"{idx}. {title}")
            formatted_results.append(f"   URL: {url}")
            if body:
                # 限制摘要長度
                snippet = body[:200] + "..." if len(body) > 200 else body
                formatted_results.append(f"   摘要: {snippet}")
            formatted_results.append("")

        result_text = "\n".join(formatted_results)

        # 添加來源提示
        result_text += "\n💡 提示：以上搜索結果來自 DuckDuckGo"

        logger.info(f"Search completed: {len(results)} results found")
        await asyncio.sleep(3)  # 避免速率限制
        return result_text

    except Exception as e:
        error_msg = f"搜索時發生錯誤: {str(e)}"
        logger.error(error_msg, exc_info=e)
        return error_msg


async def web_search_news(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
) -> str:
    """
    搜索新聞（使用 DuckDuckGo News）

    Args:
        query: 搜索查詢字串
        max_results: 最多返回結果數量（默認 5）
        region: 地區代碼

    Returns:
        格式化的新聞搜索結果
    """
    try:
        logger.info(f"Performing DuckDuckGo news search: {query}")

        def _search_news():
            with DDGS() as ddgs:
                results = list(ddgs.news(
                    query=query,
                    region=region,
                    max_results=max_results,
                    backend="auto",
                    safesearch=safe_search_default,
                ))
            return results

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _search_news)

        if not results:
            return f"未找到關於「{query}」的新聞。"

        formatted_results = []
        formatted_results.append(f"新聞搜索：{query}\n")
        formatted_results.append(f"找到 {len(results)} 則新聞：\n")

        for idx, result in enumerate(results, 1):
            title = result.get("title", "無標題")
            url = result.get("url", "")
            body = result.get("body", "")
            date = result.get("date", "")
            source = result.get("source", "")

            formatted_results.append(f"{idx}. {title}")
            if source:
                formatted_results.append(f"   來源: {source}")
            if date:
                formatted_results.append(f"   日期: {date}")
            formatted_results.append(f"   URL: {url}")
            if body:
                snippet = body[:200] + "..." if len(body) > 200 else body
                formatted_results.append(f"   摘要: {snippet}")
            formatted_results.append("")

        result_text = "\n".join(formatted_results)
        result_text += "\n💡 提示：以上新聞結果來自 DuckDuckGo News"

        logger.info(f"News search completed: {len(results)} results found")
        await asyncio.sleep(3)  # 避免速率限制
        return result_text

    except Exception as e:
        error_msg = f"新聞搜索時發生錯誤: {str(e)}"
        logger.error(error_msg, exc_info=e)
        return error_msg

async def web_search_images(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
) -> str:
    """
    搜索圖片（使用 DuckDuckGo Images）

    Args:
        query: 搜索查詢字串
        max_results: 最多返回結果數量（默認 5）
        region: 地區代碼
        
    Returns:
        格式化的圖片搜索結果
    """
    
    try:
        logger.info(f"Performing DuckDuckGo image search: {query}")

        def _search_images():
            with DDGS() as ddgs:
                results = list(ddgs.images(
                    query=query,
                    region=region,
                    max_results=max_results,
                    backend="auto",
                    safesearch=safe_search_default,
                ))
            return results
        
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _search_images)
        if not results:
            return f"未找到關於「{query}」的圖片。"
        formatted_results = []
        formatted_results.append(f"圖片搜索：{query}\n")
        formatted_results.append(f"找到 {len(results)} 張圖片：\n")
        for idx, result in enumerate(results, 1):
            title = result.get("title", "無標題")
            url = result.get("image", "")
            formatted_results.append(f"{idx}. {title}")
            formatted_results.append(f"   URL: {url}")
            formatted_results.append("")
        result_text = "\n".join(formatted_results)
        result_text += "\n💡 提示：以上圖片結果來自 DuckDuckGo"
        logger.info(f"Image search completed: {len(results)} results found")
        await asyncio.sleep(3)  # 避免速率限制
        return result_text
    except Exception as e:
        error_msg = f"圖片搜索時發生錯誤: {str(e)}"
        logger.error(error_msg, exc_info=e)
        return error_msg