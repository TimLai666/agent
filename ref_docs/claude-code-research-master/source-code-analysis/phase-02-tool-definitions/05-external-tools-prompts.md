# 05 — 外部工具 Prompt 集

> 涵蓋：WebFetchTool、WebSearchTool、MCPTool、ListMcpResourcesTool、ReadMcpResourceTool、RemoteTriggerTool、ScheduleCronTool

---

## 1. WebFetchTool（WebFetch）

**檔案**：`src/tools/WebFetchTool/prompt.ts`（46 行）

### Prompt 原文（`DESCRIPTION`）

```
- Fetches content from a specified URL and processes it using an AI model
- Takes a URL and a prompt as input
- Fetches the URL content, converts HTML to markdown
- Processes the content with the prompt using a small, fast model
- Returns the model's response about the content
- Use this tool when you need to retrieve and analyze web content

Usage notes:
  - IMPORTANT: If an MCP-provided web fetch tool is available, prefer using that tool instead of this
    one, as it may have fewer restrictions.
  - The URL must be a fully-formed valid URL
  - HTTP URLs will be automatically upgraded to HTTPS
  - The prompt should describe what information you want to extract from the page
  - This tool is read-only and does not modify any files
  - Results may be summarized if the content is very large
  - Includes a self-cleaning 15-minute cache for faster responses when repeatedly accessing the same URL
  - When a URL redirects to a different host, the tool will inform you and provide the redirect URL in
    a special format. You should then make a new WebFetch request with the redirect URL.
  - For GitHub URLs, prefer using the gh CLI via Bash instead (e.g., gh pr view, gh issue view, gh api).
```

### 二次模型處理 prompt（`makeSecondaryModelPrompt()`）

此函數對取回的內容進行二次處理，有兩個版本：

**Pre-approved domain（例如 docs.anthropic.com）：**
```
Provide a concise response based on the content above. Include relevant details, code examples,
and documentation excerpts as needed.
```

**一般 domain（含版權保護）：**
```
Provide a concise response based only on the content above. In your response:
 - Enforce a strict 125-character maximum for quotes from any source document. Open Source Software
   is ok as long as we respect the license.
 - Use quotation marks for exact language from articles; any language outside of the quotation should
   never be word-for-word the same.
 - You are not a lawyer and never comment on the legality of your own prompts and responses.
 - Never produce or reproduce exact song lyrics.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| MCP fetch 優先 | 明確指引：有 MCP fetch 工具時使用 MCP（限制更少）|
| HTTP 自動升級 HTTPS | 靜默升級，不需使用者手動修改 |
| 二次模型處理 | 取回的頁面先轉 markdown，再用小型快速模型按 prompt 提取資訊 |
| 15 分鐘快取 | 反覆存取同一 URL 不重複抓取 |
| GitHub → gh CLI | 明確的工具偏好規則 |
| 版權保護 prompt | 非 pre-approved domain 的內容有引用長度限制和版權聲明 |

---

## 2. WebSearchTool（WebSearch）

**檔案**：`src/tools/WebSearchTool/prompt.ts`（34 行）

### Prompt 原文（`getWebSearchPrompt()`，動態插入當前月份）

```
- Allows Claude to search the web and use the results to inform responses
- Provides up-to-date information for current events and recent data
- Returns search result information formatted as search result blocks, including links as markdown
  hyperlinks
- Use this tool for accessing information beyond Claude's knowledge cutoff
- Searches are performed automatically within a single API call

CRITICAL REQUIREMENT — You MUST follow this:
  - After answering the user's question, you MUST include a "Sources:" section at the end of your
    response
  - In the Sources section, list all relevant URLs from the search results as markdown hyperlinks:
    [Title](URL)
  - This is MANDATORY — never skip including sources in your response
  - Example format:

    [Your answer here]

    Sources:
    - [Source Title 1](https://example.com/1)
    - [Source Title 2](https://example.com/2)

Usage notes:
  - Domain filtering is supported to include or block specific websites
  - Web search is only available in the US

IMPORTANT — Use the correct year in search queries:
  - The current month is {currentMonthYear}. You MUST use this year when searching for recent
    information, documentation, or current events.
  - Example: If the user asks for "latest React docs", search for "React documentation" with the
    current year, NOT last year
```

### 分析

| 設計特點 | 說明 |
|---|---|
| Sources 強制必加 | "CRITICAL REQUIREMENT" + "MANDATORY"，雙重強調 |
| 地理限制 | 僅限 US，明確告知 |
| 動態年份 | `getLocalMonthYear()` 注入當前年月，防止使用過期年份搜尋 |
| 搜尋結果格式 | 以 search result blocks 形式回傳，含 markdown 超連結 |

---

## 3. MCPTool（MCPTool）

**檔案**：`src/tools/MCPTool/prompt.ts`（3 行）

### Prompt 原文

```typescript
// Actual prompt and description are overridden in mcpClient.ts
export const PROMPT = ''
export const DESCRIPTION = ''
```

### 分析

MCPTool 是個空殼。真正的 prompt 和 description 由 `mcpClient.ts` 在 MCP server 連接時動態注入（取自 MCP server 的 tool schema）。這意味著：
- 每個 MCP 工具都有自己獨立的 description
- 這些工具預設全部 defer（透過 `isDeferredTool` 規則）
- 除非設定 `_meta['anthropic/alwaysLoad']`，否則模型只有在用 ToolSearch 載入後才能呼叫

---

## 4. ListMcpResourcesTool（ListMcpResources）

**檔案**：`src/tools/ListMcpResourcesTool/prompt.ts`（20 行）

### Prompt 原文（`DESCRIPTION` 和 `PROMPT`）

**DESCRIPTION（工具 schema 描述）：**
```
Lists available resources from configured MCP servers.
Each resource object includes a 'server' field indicating which server it's from.

Usage examples:
- List all resources from all servers: `listMcpResources`
- List resources from a specific server: `listMcpResources({ server: "myserver" })`
```

**PROMPT（完整說明）：**
```
List available resources from configured MCP servers.
Each returned resource will include all standard MCP resource fields plus a 'server' field
indicating which server the resource belongs to.

Parameters:
- server (optional): The name of a specific MCP server to get resources from. If not provided,
  resources from all servers will be returned.
```

---

## 5. ReadMcpResourceTool（ReadMcpResource）

**檔案**：`src/tools/ReadMcpResourceTool/prompt.ts`（16 行）

### Prompt 原文（`DESCRIPTION` 和 `PROMPT`）

**DESCRIPTION：**
```
Reads a specific resource from an MCP server.
- server: The name of the MCP server to read from
- uri: The URI of the resource to read

Usage examples:
- Read a resource from a server: `readMcpResource({ server: "myserver", uri: "my-resource-uri" })`
```

**PROMPT：**
```
Reads a specific resource from an MCP server, identified by server name and resource URI.

Parameters:
- server (required): The name of the MCP server from which to read the resource
- uri (required): The URI of the resource to read
```

---

## 6. RemoteTriggerTool（RemoteTrigger）

**檔案**：`src/tools/RemoteTriggerTool/prompt.ts`（15 行）

### Prompt 原文（`PROMPT`）

```
Call the claude.ai remote-trigger API. Use this instead of curl — the OAuth token is added
automatically in-process and never exposed.

Actions:
- list: GET /v1/code/triggers
- get: GET /v1/code/triggers/{trigger_id}
- create: POST /v1/code/triggers (requires body)
- update: POST /v1/code/triggers/{trigger_id} (requires body, partial update)
- run: POST /v1/code/triggers/{trigger_id}/run

The response is the raw JSON from the API.
```

**DESCRIPTION：**
```
Manage scheduled remote Claude Code agents (triggers) via the claude.ai CCR API. Auth is handled
in-process — the token never reaches the shell.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| Token 安全性 | 明確說明「token 在 in-process 處理，永不暴露」——禁止使用者透過 curl 自行做 |
| 原始 API CRUD | 直接對應 REST API 的 list/get/create/update/run |
| 與 ScheduleCron 的關係 | RemoteTrigger = 管理 remote CCR agent 觸發器；ScheduleCron = 管理本地 session cron |

---

## 7. ScheduleCronTool（CronCreate / CronDelete / CronList）

**檔案**：`src/tools/ScheduleCronTool/prompt.ts`（135 行）

### CronCreate Prompt 原文（`buildCronCreatePrompt()`）

```
Schedule a prompt to be enqueued at a future time. Use for both recurring schedules and one-shot
reminders.

Uses standard 5-field cron in the user's local timezone: minute hour day-of-month month day-of-week.
"0 9 * * *" means 9am local — no timezone conversion needed.

## One-shot tasks (recurring: false)

For "remind me at X" or "at <time>, do Y" requests — fire once then auto-delete.
Pin minute/hour/day-of-month/month to specific values:
  "remind me at 2:30pm today" → cron: "30 14 <today_dom> <today_month> *", recurring: false
  "tomorrow morning, run the smoke test" → cron: "57 8 <tomorrow_dom> <tomorrow_month> *"

## Recurring jobs (recurring: true, the default)

For "every N minutes" / "every hour" / "weekdays at 9am" requests:
  "*/5 * * * *" (every 5 min), "0 * * * *" (hourly), "0 9 * * 1-5" (weekdays at 9am local)

## Avoid the :00 and :30 minute marks when the task allows it

Every user who asks for "9am" gets `0 9`, and every user who asks for "hourly" gets `0 *` — which
means requests from across the planet land on the API at the same instant. When the user's request
is approximate, pick a minute that is NOT 0 or 30:
  "every morning around 9" → "57 8 * * *" or "3 9 * * *" (not "0 9 * * *")
  "hourly" → "7 * * * *" (not "0 * * * *")

Only use minute 0 or 30 when the user names that exact time clearly.

## Durability [isDurableCronEnabled() = true]

By default (durable: false) the job lives only in this Claude session — nothing is written to disk,
and the job is gone when Claude exits. Pass durable: true to write to .claude/scheduled_tasks.json
so the job survives restarts. Only use durable: true when the user explicitly asks for persistence.

## Runtime behavior

Jobs only fire while the REPL is idle (not mid-query). [Durable note if enabled]
The scheduler adds a small deterministic jitter: recurring tasks fire up to 10% of their period late
(max 15 min); one-shot tasks landing on :00 or :30 fire up to 90s early.

Recurring tasks auto-expire after {DEFAULT_MAX_AGE_DAYS} days — they fire one final time, then are
deleted. Tell the user about this limit when scheduling recurring jobs.

Returns a job ID you can pass to CronDelete.
```

### CronDelete Prompt
```
Cancel a cron job previously scheduled with CronCreate. Removes it from .claude/scheduled_tasks.json
(durable jobs) or the in-memory session store (session-only jobs).
```

### CronList Prompt
```
List all cron jobs scheduled via CronCreate, both durable and session-only.
```

### Gate 機制

```typescript
// 兩層 gate：build-time feature flag + runtime GrowthBook
function isKairosCronEnabled(): boolean {
  return feature('AGENT_TRIGGERS')
    ? !isEnvTruthy(process.env.CLAUDE_CODE_DISABLE_CRON) &&
        getFeatureValue_CACHED_WITH_REFRESH('tengu_kairos_cron', true, 5分鐘)
    : false
}

// durable 功能獨立 gate
function isDurableCronEnabled(): boolean {
  return getFeatureValue_CACHED_WITH_REFRESH('tengu_kairos_cron_durable', true, 5分鐘)
}
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 時區安全 | 5-field cron 使用本地時區，不需換算 |
| 避免 :00/:30 | 明確的「fleet 負載均衡」考慮，分散請求 |
| 抖動設計 | scheduler 會在 cron 時間附近加隨機延遲，防止所有使用者同時觸發 |
| 自動過期 | recurring tasks 有 `DEFAULT_MAX_AGE_DAYS` 上限（防止 session 無限累積）|
| session vs durable | 預設 session-only；persistence 需明確使用者請求 |
| kill switch | GrowthBook `tengu_kairos_cron` = false 可即時停止 fleet 上所有 scheduler |

---

## 外部工具安全對比

| 工具 | 限制類型 | 安全機制 |
|---|---|---|
| WebFetch | 版權保護、GitHub 偏好 | 引用長度上限、二次模型過濾、pre-approved domain 分級 |
| WebSearch | 地理、強制 Sources | 僅限 US；必加 Sources section；動態年份注入 |
| MCPTool | defer 預設 | schema 需 ToolSearch 載入；運行時才有 description |
| ListMcpResources | 無特殊 | 可按 server 篩選 |
| ReadMcpResource | 需明確 server + uri | 無 |
| RemoteTrigger | OAuth token 保護 | in-process 處理，不允許 curl 繞過 |
| CronCreate | 時間範圍、自動過期 | session/durable 分級；GrowthBook kill switch；`DEFAULT_MAX_AGE_DAYS` 上限 |
