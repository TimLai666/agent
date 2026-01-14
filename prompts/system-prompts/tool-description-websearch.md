<!--
name: 'Tool Description: WebSearch'
description: Tool description for web search functionality (including general, news, and image search)
ccVersion: 2.0.56
variables:
  - GET_CURRENT_DATE_FN
-->

# 網路搜尋工具 (Web Search Tools)

你有**三種**網路搜尋工具可以使用，全部使用 DuckDuckGo（完全免費，無需 API key）：

## 1. web_search - 一般網路搜尋

**用途**: 搜尋一般資訊、技術文件、教學、網站內容等

**使用時機**:

- 需要搜尋最新資訊、技術文件或教學
- 尋找特定主題的網頁內容
- 獲取超出知識截止日期的資訊
- 需要多個來源的綜合資訊

**參數**:

- `query`: 搜尋查詢字串
- `max_results`: 最多返回結果數量（默認 5）
- `region`: 地區代碼（默認 wt-wt 為全球，zh-tw 為台灣，zh-cn 為中國）

**返回內容**: 標題、URL、內容摘要

## 2. web_search_news - 新聞搜尋

**用途**: 搜尋最新新聞、時事報導、新聞文章

**使用時機**:

- 用戶詢問「最新新聞」、「近期發生的事」
- 需要時效性強的資訊（今天、本週、最近的事件）
- 尋找新聞報導或媒體文章
- 需要了解當前熱門話題或突發事件

**參數**:

- `query`: 搜尋查詢字串
- `max_results`: 最多返回結果數量（默認 5）
- `region`: 地區代碼

**返回內容**: 標題、URL、摘要、**發布日期**、**新聞來源**

## 3. web_search_images - 圖片搜尋

**用途**: 搜尋圖片、照片、視覺內容

**使用時機**:

- 用戶詢問「找圖片」、「圖片搜尋」
- 需要視覺參考資料
- 尋找特定主題的圖像
- 需要提供圖片 URL 給用戶

**參數**:

- `query`: 搜尋查詢字串
- `max_results`: 最多返回結果數量（默認 5）
- `region`: 地區代碼

**返回內容**: 圖片標題、圖片 URL

---

## 如何選擇使用哪個工具？

```text
用戶問：「Python 教學」
→ 使用 web_search (一般資訊搜尋)

用戶問：「今天有什麼新聞？」
→ 使用 web_search_news (新聞搜尋)

用戶問：「找一些貓咪的圖片」
→ 使用 web_search_images (圖片搜尋)

用戶問：「最新的 AI 發展」
→ 使用 web_search_news (時效性強，新聞更合適)

用戶問：「React 官方文件」
→ 使用 web_search (技術文件)
```

---

## 重要使用規範

### CRITICAL REQUIREMENT - 引用來源

使用任何搜尋工具後，你**必須**在回答末尾加上「Sources:」部分：

```text
[你的回答內容]

Sources:
- [來源標題 1](https://example.com/1)
- [來源標題 2](https://example.com/2)
```

**這是強制要求 - 絕不可省略來源引用！**

### 搜尋查詢注意事項

**使用正確的年份**:

- 今天的日期是 ${GET_CURRENT_DATE_FN()}
- 搜尋近期資訊時，**必須**使用當前年份
- ❌ 錯誤: "React documentation 2024"
- ✅ 正確: "React documentation 2025"（如果當前是 2025 年）

### 其他注意事項

- 所有搜尋工具都使用 **DuckDuckGo**，完全免費且無需 API key
- 支援地區過濾（region 參數）
- 每個工具都會在結果末尾標註來源（DuckDuckGo / DuckDuckGo News）
- 搜尋結果會自動限制摘要長度（200 字元）以保持簡潔
