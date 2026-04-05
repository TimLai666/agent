# Cache Invalidation Verification — Why MCP Tool Discovery Doesn't Actually Bust the Prompt Cache
# 快取失效驗證 — 為什麼 MCP 工具的載入不會破壞提示快取

[English Version](./report-en.md) | [繁體中文版](./report-zh.md)

---

## What This Report Covers / 這篇報告在講什麼

We predicted that discovering an MCP tool via ToolSearch would invalidate the entire prompt cache — the tools array changes, the prefix shifts, and everything gets rewritten at 125% cost. A live experiment at 283k context tokens showed no cost change at all. This report traces the full investigation through CLI v2.1.85 source code, 15+ GitHub issues, and Anthropic's official API documentation to explain why: the `defer_loading` flag fundamentally changes how the server treats tool definitions in the cache prefix. Deferred tools are excluded from the prefix entirely. But non-deferred tools, system prompt changes, and six other scenarios still trigger real cache invalidation — this report maps all of them.

我們原本預測：透過 ToolSearch 載入 MCP 工具會讓整個提示快取失效——工具陣列改變、前綴偏移、所有內容以 125% 成本重新寫入。但在 283k token 的對話中實測，/cost 完全沒有變動。本報告完整追蹤了這次調查：逆向 CLI v2.1.85 原始碼、搜尋 15+ 個 GitHub issue、閱讀 Anthropic 官方 API 文件，最終解答了原因：`defer_loading` 這個旗標從根本上改變了伺服器處理工具定義的方式，延遲載入的工具被完全排除在快取前綴之外。但非延遲工具、系統提示變更、以及另外六種操作仍然會觸發真正的快取失效——本報告逐一整理了所有情境。

## Who Should Read This / 適合誰讀

- **Claude Code power users** — understand exactly which actions cost you extra tokens and which are safe
- **重度 Claude Code 使用者** — 搞清楚哪些操作會多燒 token、哪些不會

- **MCP integration developers** — learn why deferred loading is cache-safe by design, not by accident
- **MCP 整合開發者** — 理解為什麼延遲載入在設計上就是快取安全的

- **API cost engineers** — get a complete scenario-by-scenario cost impact map with estimation formulas
- **API 成本工程師** — 取得完整的操作情境成本表與估算公式

- **Claude Code researchers** — see the full cache architecture of CLI v2.1.85 with source code evidence
- **Claude Code 研究者** — 看到 CLI v2.1.85 完整的快取架構與原始碼佐證

## What You'll Learn / 你會學到什麼

- Why the prediction "MCP tool discovery busts cache" was wrong, and the exact point where the reasoning broke
- 為什麼「MCP 工具載入會破壞快取」的預測是錯的，以及推理鏈在哪個環節斷裂

- The complete cache breakpoint map: which parts of the API request get `cache_control` and which don't
- 完整的快取斷點分布圖：API 請求中哪些部分有 `cache_control`、哪些沒有

- Three distinct cache strategies inside the system prompt processor, and what triggers each one
- 系統提示處理器中的三種快取策略，以及各自的觸發條件

- The full deferred tool loading pipeline: from registration to API request to server-side expansion
- 延遲工具載入的完整流程：從註冊、到 API 請求、到伺服器端展開

- Six types of evidence proving deferred tools don't participate in cache prefix calculation
- 六項證據證明延遲工具不參與快取前綴的計算

- A practical scenario guide: every operation that does or doesn't bust cache, with cost estimates
- 實用操作指南：每一種會或不會觸發快取失效的操作，附成本估算
