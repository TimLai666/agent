# 04 — Beta Features 完整清單與分析

來源：`src/constants/betas.ts`、`src/utils/betas.ts`（間接）

---

## 1. 所有 Beta Header 常數

```typescript
// src/constants/betas.ts

CLAUDE_CODE_20250219_BETA_HEADER   = 'claude-code-20250219'
INTERLEAVED_THINKING_BETA_HEADER   = 'interleaved-thinking-2025-05-14'
CONTEXT_1M_BETA_HEADER             = 'context-1m-2025-08-07'
CONTEXT_MANAGEMENT_BETA_HEADER     = 'context-management-2025-06-27'
STRUCTURED_OUTPUTS_BETA_HEADER     = 'structured-outputs-2025-12-15'
WEB_SEARCH_BETA_HEADER             = 'web-search-2025-03-05'
TOOL_SEARCH_BETA_HEADER_1P         = 'advanced-tool-use-2025-11-20'   // 1P / Foundry
TOOL_SEARCH_BETA_HEADER_3P         = 'tool-search-tool-2025-10-19'    // Vertex / Bedrock
EFFORT_BETA_HEADER                 = 'effort-2025-11-24'
TASK_BUDGETS_BETA_HEADER           = 'task-budgets-2026-03-13'
PROMPT_CACHING_SCOPE_BETA_HEADER   = 'prompt-caching-scope-2026-01-05'
FAST_MODE_BETA_HEADER              = 'fast-mode-2026-02-01'
REDACT_THINKING_BETA_HEADER        = 'redact-thinking-2026-02-12'
TOKEN_EFFICIENT_TOOLS_BETA_HEADER  = 'token-efficient-tools-2026-03-28'
ADVISOR_BETA_HEADER                = 'advisor-tool-2026-03-01'

// 條件性（feature flag 控制）
SUMMARIZE_CONNECTOR_TEXT_BETA_HEADER = feature('CONNECTOR_TEXT')
  ? 'summarize-connector-text-2026-03-13' : ''

AFK_MODE_BETA_HEADER               = feature('TRANSCRIPT_CLASSIFIER')
  ? 'afk-mode-2026-01-31' : ''

CLI_INTERNAL_BETA_HEADER           = USER_TYPE === 'ant'
  ? 'cli-internal-2026-02-09' : ''
```

---

## 2. Beta 功能詳細說明

### `claude-code-20250219`（基礎 Claude Code Beta）
- 所有 Claude Code 請求都帶此 header
- 啟用 Claude Code 專屬的 API 行為（system prompt 格式等）

### `interleaved-thinking-2025-05-14`（交叉思考）
- 啟用思考區塊與回應文字的交叉輸出
- Bedrock 需放在 `extraBodyParams.anthropic_beta`（不能放 HTTP header）

### `context-1m-2025-08-07`（1M Context Window）
- 啟用 1M token 的上下文視窗
- 在 `paramsFromContext` 中動態追加（當 getSonnet1mExpTreatmentEnabled() 為 true）
- Bedrock 需放在 `extraBodyParams`

### `context-management-2025-06-27`（上下文管理）
- 啟用 `context_management` API 欄位
- 控制 thinking token 的保留策略（keep-all vs clear）

### `structured-outputs-2025-12-15`（結構化輸出）
- 啟用 `output_config.format` 欄位
- 僅在 `modelSupportsStructuredOutputs(model)` 為 true 時添加

### `web-search-2025-03-05`（Web 搜尋）
- 啟用 web 搜尋工具支援

### `advanced-tool-use-2025-11-20` / `tool-search-tool-2025-10-19`（Tool Search）
- 啟用 `defer_loading` 工具屬性
- 1P/Foundry 用 `advanced-tool-use`，Bedrock/Vertex 用 `tool-search-tool`
- Bedrock 需放在 `extraBodyParams`

### `effort-2025-11-24`（Effort 控制）
- 啟用 `output_config.effort` 欄位
- 值可為 `'low'` | `'medium'` | `'high'` | `'max'`（字串）
- ant 用戶可指定數值 effort（透過 `anthropic_internal.effort_override`）

### `task-budgets-2026-03-13`（Task Budget）
- 啟用 `output_config.task_budget`（token 總量和剩餘量）
- 讓模型知道自己的 token 預算以便調整輸出節奏
- 僅在 `shouldIncludeFirstPartyOnlyBetas()` 時添加（1P only）

### `prompt-caching-scope-2026-01-05`（Global Cache Scope）
- 啟用 `cache_control.scope: 'global'`
- 系統提示在跨用戶之間共享快取（而非僅限同一用戶）
- 需 `shouldUseGlobalCacheScope()` 判斷（subscriber + 非 MCP 工具場景）

### `fast-mode-2026-02-01`（Fast Mode）
- 啟用 `speed: 'fast'` 請求參數
- Header 使用 latch 機制（sticky-on）以避免破壞 prompt cache
- `speed` body param 仍動態（cooldown 時不帶 speed='fast'，但 header 仍送）

### `redact-thinking-2026-02-12`（Redact Thinking）
- 啟用 thinking token 的隱藏/過濾
- 與 `thinkingClearLatched` 搭配使用（>1h 無 API 呼叫時清除 thinking）

### `token-efficient-tools-2026-03-28`（Token 高效工具）
- 減少工具呼叫的 token 使用量
- 最新 beta，2026-03-28 引入

### `advisor-tool-2026-03-01`（Advisor Tool）
- 啟用 server-side advisor（`type: 'advisor_20260301'`）
- 讓另一個 Claude 模型作為 advisor 在同一次請求中提供建議
- 即使非 agentic query，只要 `isAdvisorEnabled()` 即添加（以解析歷史中的 advisor blocks）

### `afk-mode-2026-01-31`（AFK / Auto Mode）
- 僅在 `feature('TRANSCRIPT_CLASSIFIER')` 和 auto mode 首次啟用時添加
- 使用 latch 機制（sticky-on）
- 告知 API 目前處於 auto/AFK 模式

### `cli-internal-2026-02-09`（CLI Internal）
- 僅限 `USER_TYPE === 'ant'`（Anthropic 員工）
- 啟用內部 API 功能

### `summarize-connector-text-2026-03-13`（Connector Text 摘要）
- 需 `feature('CONNECTOR_TEXT')` build flag
- 啟用 connector_text 類型的內容區塊

---

## 3. Bedrock 特殊處理

```typescript
export const BEDROCK_EXTRA_PARAMS_HEADERS = new Set([
  'interleaved-thinking-2025-05-14',
  'context-1m-2025-08-07',
  'tool-search-tool-2025-10-19',
])
```

這三個 header 在 Bedrock 上必須透過 `extraBodyParams.anthropic_beta` 傳遞，而非 HTTP `anthropic-beta` header。

---

## 4. Beta 分配邏輯

### getMergedBetas（來自 utils/betas.ts）

Beta headers 的主要組裝點，負責：

1. 取得 model-specific betas（`getModelBetas(model)`）
2. 根據 `isAgenticQuery` 添加 context management beta
3. 根據 tool search 狀態添加對應 header
4. 根據 `shouldIncludeFirstPartyOnlyBetas()` 添加 1P-only betas

### 條件送出矩陣

| Beta | 條件 |
|---|---|
| claude-code-20250219 | 始終（model betas） |
| context-1m | 動態（Sonnet 1M 實驗 or 模型支援） |
| context-management | isAgenticQuery |
| prompt-caching-scope | shouldUseGlobalCacheScope() |
| fast-mode | fastModeHeaderLatched（sticky-on） |
| afk-mode | afkHeaderLatched AND isAgenticQuery AND shouldIncludeFirstPartyOnlyBetas |
| task-budgets | shouldIncludeFirstPartyOnlyBetas AND 有 taskBudget |
| advisor | isAdvisorEnabled() |
| effort | modelSupportsEffort(model) |
| structured-outputs | modelSupportsStructuredOutputs(model) AND outputFormat 指定 |
| token-efficient-tools | model betas（若模型支援） |
