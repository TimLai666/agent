# Auto Mode Classifier Cost — Every Tool Use Triggers a Hidden LLM Call at Your Expense
# Auto Mode 分類器成本 — 每次工具操作都在背後多發一次 LLM 請求

[English Version](./report-en.md) | [繁體中文版](./report-zh.md)

---

## What This Report Covers / 這篇報告在講什麼

Claude Code's Auto Mode makes a hidden API call before every side-effecting tool use — Edit, Write, Bash, MCP tools — to classify whether the action should be allowed. In v2.1.88, the classifier model was changed to inherit the main conversation model: Max subscribers now run Opus for classification, paying ~5× more per call than the previous hardcoded Sonnet. The classifier receives a condensed transcript of the entire conversation (including Read/Grep history), and only the fixed portions benefit from prompt caching. A Statsig-controlled flag can silently double the classifier calls with no user override. This report reverse-engineers the complete mechanism and maps the cost impact.

Claude Code 的 Auto Mode 在每一次有副作用的工具操作前，都會暗中發一次 API 請求來判斷是否放行。在 v2.1.88，分類器的模型改為繼承主對話模型：Max 訂閱用戶現在用 Opus 做分類，每次呼叫的成本是之前寫死的 Sonnet 的約 5 倍。分類器會收到整段對話的精簡版（包含 Read/Grep 的歷史），而且只有固定不變的部分能被快取。Statsig 遠端還能靜默地把分類器呼叫翻倍，使用者完全無法控制。本報告完整逆向了這個機制，並整理了成本影響。

## Who Should Read This / 適合誰讀

- **Claude Code Auto Mode users** — understand the hidden cost of "automatic" permission
- **Auto Mode 使用者** — 搞清楚「自動」權限背後的隱藏成本

- **Max subscribers** — learn why your quota burns faster in Auto Mode than manual approval
- **Max 訂閱用戶** — 了解為什麼 Auto Mode 比手動確認更快燒完額度

- **Claude Code researchers** — complete reverse-engineering of the classifier pipeline in v2.1.88
- **Claude Code 研究者** — v2.1.88 分類器管線的完整逆向分析

## What You'll Learn / 你會學到什麼

- The complete classifier flow: when it fires, what it sends, and how the model is selected
- 完整的分類器流程：什麼時候觸發、送了什麼、模型怎麼選的

- Why Max users pay ~5× more per classifier call than in previous versions
- 為什麼 Max 用戶每次分類器呼叫的成本比之前多約 5 倍

- The cache structure and why it only covers ~10–45% of classifier input depending on session length
- 快取結構，以及為什麼依對話長度只能覆蓋 10–45% 的分類器 input

- How the two-stage classifier doubles API calls via a remote feature flag you can't control
- Two-stage classifier 如何透過你無法控制的遠端開關把 API 呼叫翻倍

- Four mitigation options from zero-modification settings to cli.js patches
- 四種緩解方案，從零修改的設定到 cli.js patch
