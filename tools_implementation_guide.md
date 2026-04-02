# 網路搜尋與瀏覽工具實作指南

本指南提供完整的網路搜尋和網頁獲取工具實作方案，讓你的 agent 具備與 Claude Code 相同的網路能力。

---

## 架構概覽

```
Agent
├─ WebSearch 工具 - 搜尋引擎整合
│   ├─ 搜尋 API (Google/Bing/Brave/DuckDuckGo)
│   ├─ 結果解析和過濾
│   └─ 格式化輸出
│
└─ WebFetch 工具 - 網頁內容獲取
    ├─ HTTP 請求 (requests/httpx)
    ├─ HTML 轉 Markdown (html2text/markdownify)
    └─ 內容處理 (選用 AI 摘要)
```

---

## 方案 1: 使用 Google Custom Search API (推薦)

### 優點
- ✅ 官方支援，穩定可靠
- ✅ 搜尋品質高
- ✅ 每天 100 次免費配額
- ✅ 支援多語言

### 缺點
- ❌ 超過配額需付費
- ❌ 需要 API key 和 Search Engine ID

### 實作步驟

#### 1. 取得 API 憑證

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立專案並啟用 "Custom Search API"
3. 建立 API 金鑰
4. 前往 [Programmable Search Engine](https://programmablesearchengine.google.com/)
5. 建立搜尋引擎，取得 Search Engine ID (cx)

#### 2. Python 實作範例

```python
import requests
from typing import List, Dict, Optional

class WebSearchTool:
    """Google Custom Search API 網路搜尋工具"""

    def __init__(self, api_key: str, search_engine_id: str):
        self.api_key = api_key
        self.cx = search_engine_id
        self.base_url = "https://www.googleapis.com/customsearch/v1"

    def search(
        self,
        query: str,
        num_results: int = 10,
        language: str = "zh-TW",
        allowed_domains: Optional[List[str]] = None,
        blocked_domains: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        執行網路搜尋

        Args:
            query: 搜尋關鍵字
            num_results: 返回結果數量 (最多 10)
            language: 語言設定
            allowed_domains: 只搜尋這些網域
            blocked_domains: 排除這些網域

        Returns:
            搜尋結果列表，每個結果包含 title, link, snippet
        """
        # 構建查詢參數
        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query,
            "num": min(num_results, 10),
            "lr": f"lang_{language.replace('-', '_')}"
        }

        # 網域過濾
        if allowed_domains:
            site_filter = " OR ".join([f"site:{domain}" for domain in allowed_domains])
            params["q"] = f"{query} ({site_filter})"

        if blocked_domains:
            for domain in blocked_domains:
                params["q"] += f" -site:{domain}"

        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # 解析結果
            results = []
            for item in data.get("items", []):
                results.append({
                    "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "displayLink": item.get("displayLink", "")
                })

            return results

        except requests.RequestException as e:
            print(f"搜尋失敗: {e}")
            return []

    def format_results(self, results: List[Dict]) -> str:
        """格式化搜尋結果為可讀文字"""
        if not results:
            return "未找到相關結果。"

        output = []
        for i, result in enumerate(results, 1):
            output.append(f"{i}. **{result['title']}**")
            output.append(f"   {result['snippet']}")
            output.append(f"   🔗 {result['link']}")
            output.append("")

        return "\n".join(output)


# 使用範例
if __name__ == "__main__":
    # 初始化工具
    search_tool = WebSearchTool(
        api_key="YOUR_API_KEY",
        search_engine_id="YOUR_SEARCH_ENGINE_ID"
    )

    # 執行搜尋
    results = search_tool.search(
        query="Claude AI 最新功能",
        num_results=5,
        language="zh-TW"
    )

    # 顯示結果
    print(search_tool.format_results(results))
```

---

## 方案 2: 使用 Brave Search API (免費額度更多)

### 優點
- ✅ 每月 2000 次免費請求
- ✅ 注重隱私
- ✅ 搜尋品質不錯
- ✅ 支援網頁、新聞、圖片搜尋

### 缺點
- ❌ 相對較新，生態較小

### 實作範例

```python
import requests
from typing import List, Dict, Optional

class BraveSearchTool:
    """Brave Search API 網路搜尋工具"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    def search(
        self,
        query: str,
        count: int = 10,
        language: str = "zh-TW"
    ) -> List[Dict]:
        """執行搜尋"""
        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json"
        }

        params = {
            "q": query,
            "count": count,
            "country": "TW",
            "search_lang": language.split("-")[0]
        }

        try:
            response = requests.get(
                self.base_url,
                headers=headers,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "link": item.get("url", ""),
                    "snippet": item.get("description", ""),
                    "displayLink": item.get("url", "").split("/")[2]
                })

            return results

        except requests.RequestException as e:
            print(f"搜尋失敗: {e}")
            return []

# 註冊: https://brave.com/search/api/
```

---

## 方案 3: 使用 DuckDuckGo (完全免費)

### 優點
- ✅ 完全免費，無需 API key
- ✅ 注重隱私
- ✅ 無配額限制

### 缺點
- ❌ 非官方 API，可能不穩定
- ❌ 需要使用第三方套件

### 實作範例

```python
from duckduckgo_search import DDGS
from typing import List, Dict

class DuckDuckGoSearchTool:
    """DuckDuckGo 搜尋工具 (免費)"""

    def search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "wt-wt"  # 世界範圍，或 "tw-zh" 台灣
    ) -> List[Dict]:
        """執行搜尋"""
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    query,
                    region=region,
                    max_results=max_results
                ))

                formatted_results = []
                for result in results:
                    formatted_results.append({
                        "title": result.get("title", ""),
                        "link": result.get("href", ""),
                        "snippet": result.get("body", ""),
                        "displayLink": result.get("href", "").split("/")[2]
                    })

                return formatted_results

        except Exception as e:
            print(f"搜尋失敗: {e}")
            return []

# 安裝: pip install duckduckgo-search
```

---

## WebFetch 工具實作

### 基礎版本 (使用 requests + html2text)

```python
import requests
import html2text
from typing import Optional

class WebFetchTool:
    """網頁內容獲取工具"""

    def __init__(self):
        self.html2text = html2text.HTML2Text()
        self.html2text.ignore_links = False
        self.html2text.ignore_images = True
        self.html2text.body_width = 0  # 不換行

    def fetch(
        self,
        url: str,
        max_length: int = 50000
    ) -> Optional[str]:
        """
        獲取網頁內容並轉換為 Markdown

        Args:
            url: 網頁 URL
            max_length: 最大內容長度

        Returns:
            Markdown 格式的網頁內容，失敗返回 None
        """
        try:
            # 發送請求
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            # 自動升級 HTTP 到 HTTPS
            if url.startswith("http://"):
                upgraded_url = url.replace("http://", "https://", 1)
                response = requests.get(upgraded_url, headers=headers, timeout=15)
                response.raise_for_status()

            # 轉換為 Markdown
            markdown = self.html2text.handle(response.text)

            # 限制長度
            if len(markdown) > max_length:
                markdown = markdown[:max_length] + "\n\n[內容過長已截斷...]"

            return markdown

        except requests.RequestException as e:
            print(f"獲取網頁失敗: {e}")
            return None

    def fetch_with_prompt(
        self,
        url: str,
        prompt: str,
        llm_client=None
    ) -> str:
        """
        獲取網頁並用 LLM 處理內容

        Args:
            url: 網頁 URL
            prompt: 要對內容提出的問題
            llm_client: LLM 客戶端 (如 OpenAI client)

        Returns:
            LLM 處理後的回應
        """
        content = self.fetch(url)
        if not content:
            return "無法獲取網頁內容"

        if llm_client:
            # 使用 LLM 處理內容
            full_prompt = f"""網頁內容：\n\n{content}\n\n問題：{prompt}"""

            # 這裡需要根據你的 LLM 客戶端調整
            response = llm_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": full_prompt}
                ]
            )
            return response.choices[0].message.content
        else:
            # 沒有 LLM，直接返回內容
            return f"網頁內容：\n\n{content}"

# 安裝: pip install requests html2text
```

### 進階版本 (使用 playwright 處理 JavaScript)

```python
from playwright.sync_api import sync_playwright
import html2text

class AdvancedWebFetchTool:
    """進階網頁獲取工具 (支援 JavaScript 渲染)"""

    def __init__(self):
        self.html2text = html2text.HTML2Text()
        self.html2text.ignore_links = False
        self.html2text.ignore_images = True

    def fetch(self, url: str, wait_for: str = None) -> str:
        """
        使用瀏覽器獲取網頁內容

        Args:
            url: 網頁 URL
            wait_for: 等待特定元素出現 (CSS selector)
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                page.goto(url, wait_until="networkidle")

                if wait_for:
                    page.wait_for_selector(wait_for, timeout=5000)

                html_content = page.content()
                markdown = self.html2text.handle(html_content)

                return markdown

            finally:
                browser.close()

# 安裝: pip install playwright html2text
# 初始化: playwright install chromium
```

---

## 整合到你的 Agent

### 1. 定義工具 Schema

```python
tools = [
    {
        "name": "web_search",
        "description": "搜尋網路以獲取最新資訊。使用這個工具來查找時事、新聞、產品資訊、技術文件等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜尋關鍵字"
                },
                "num_results": {
                    "type": "integer",
                    "description": "返回結果數量",
                    "default": 10
                },
                "allowed_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "只搜尋這些網域 (可選)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_fetch",
        "description": "獲取指定 URL 的網頁內容。用於讀取文章、文件、API 文件等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要獲取的網頁 URL"
                },
                "prompt": {
                    "type": "string",
                    "description": "對網頁內容提出的問題或需要提取的資訊"
                }
            },
            "required": ["url", "prompt"]
        }
    }
]
```

### 2. 工具處理函數

```python
def handle_tool_call(tool_name: str, tool_input: dict) -> str:
    """處理工具調用"""

    if tool_name == "web_search":
        # 使用你選擇的搜尋工具
        search_tool = WebSearchTool(
            api_key=os.getenv("GOOGLE_API_KEY"),
            search_engine_id=os.getenv("SEARCH_ENGINE_ID")
        )

        results = search_tool.search(
            query=tool_input["query"],
            num_results=tool_input.get("num_results", 10),
            allowed_domains=tool_input.get("allowed_domains")
        )

        return search_tool.format_results(results)

    elif tool_name == "web_fetch":
        fetch_tool = WebFetchTool()

        content = fetch_tool.fetch_with_prompt(
            url=tool_input["url"],
            prompt=tool_input["prompt"],
            llm_client=your_llm_client  # 你的 LLM 客戶端
        )

        return content

    return "未知的工具"
```

### 3. 在 Agent 循環中使用

```python
def agent_loop(user_message: str):
    """Agent 主循環"""

    messages = [{"role": "user", "content": user_message}]

    while True:
        # 調用 LLM
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            tools=tools,
            messages=messages
        )

        # 檢查是否需要調用工具
        if response.stop_reason == "tool_use":
            # 找出工具調用
            tool_use = next(
                block for block in response.content
                if block.type == "tool_use"
            )

            # 執行工具
            tool_result = handle_tool_call(
                tool_name=tool_use.name,
                tool_input=tool_use.input
            )

            # 添加工具結果到對話
            messages.append({
                "role": "assistant",
                "content": response.content
            })
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": tool_result
                }]
            })

            # 繼續循環
            continue

        else:
            # 完成，返回最終回應
            return response.content[0].text
```

---

## 快速開始：最小實作

如果你想快速開始，這裡是最簡單的實作：

```python
# 安裝依賴
# pip install duckduckgo-search requests html2text

from duckduckgo_search import DDGS
import requests
import html2text

def web_search(query: str, max_results: int = 10):
    """簡單的網路搜尋"""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
        return results

def web_fetch(url: str):
    """簡單的網頁獲取"""
    h = html2text.HTML2Text()
    response = requests.get(url, timeout=10)
    return h.handle(response.text)

# 測試
if __name__ == "__main__":
    # 搜尋測試
    results = web_search("Python 教學")
    for r in results[:3]:
        print(f"{r['title']}: {r['href']}")

    # 獲取測試
    content = web_fetch("https://www.python.org")
    print(content[:500])
```

---

## 建議的搜尋 API 選擇

| 需求 | 推薦方案 | 原因 |
|-----|---------|------|
| 個人專案/學習 | DuckDuckGo | 完全免費 |
| 小型專案 | Brave Search | 每月 2000 次免費 |
| 商業專案 | Google Custom Search | 品質最好，穩定可靠 |
| 需要 JS 渲染 | Playwright + 任一搜尋 | 完整瀏覽器環境 |

---

## 進階功能

### 1. 搜尋結果快取

```python
import json
from pathlib import Path
from datetime import datetime, timedelta

class CachedWebSearch:
    """帶快取的搜尋工具"""

    def __init__(self, search_tool, cache_dir="./search_cache"):
        self.search_tool = search_tool
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def search(self, query: str, cache_hours: int = 24, **kwargs):
        """搜尋，優先使用快取"""
        cache_file = self.cache_dir / f"{hash(query)}.json"

        # 檢查快取
        if cache_file.exists():
            with open(cache_file) as f:
                data = json.load(f)
                cache_time = datetime.fromisoformat(data["timestamp"])

                if datetime.now() - cache_time < timedelta(hours=cache_hours):
                    print(f"使用快取結果 (來自 {cache_time})")
                    return data["results"]

        # 執行搜尋
        results = self.search_tool.search(query, **kwargs)

        # 儲存快取
        with open(cache_file, "w") as f:
            json.dump({
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "results": results
            }, f, ensure_ascii=False, indent=2)

        return results
```

### 2. 智能結果過濾

```python
def filter_search_results(results: List[Dict], keywords: List[str]) -> List[Dict]:
    """根據關鍵字過濾搜尋結果"""
    filtered = []
    for result in results:
        text = f"{result['title']} {result['snippet']}".lower()
        if any(keyword.lower() in text for keyword in keywords):
            filtered.append(result)
    return filtered
```

---

## 總結

最推薦的組合：
1. **快速開始**: DuckDuckGo (免費) + requests + html2text
2. **生產環境**: Google Custom Search API + requests + html2text
3. **複雜網站**: Playwright + Brave Search API

祝你的 agent 獲得強大的網路能力！🚀
