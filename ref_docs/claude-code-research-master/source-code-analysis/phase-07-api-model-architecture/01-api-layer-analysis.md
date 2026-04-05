# 01 — API 呼叫層完整分析

來源：`src/services/api/claude.ts`（3419 行）

---

## 1. 模組角色

`claude.ts` 是整個 Claude Code 對 Anthropic API 的唯一呼叫閘道，實作：

- 請求組裝（system prompt、messages、tools、betas、output_config）
- 串流讀取與回應解析
- Prompt caching 策略
- 非串流 fallback
- 重試邏輯（委派 `withRetry.ts`）
- 媒體數量限制防護

---

## 2. 核心型別

```typescript
export type Options = {
  model: string
  querySource: QuerySource
  tools: Tools
  mcpTools: Tools
  agents: AgentDefinition[]
  isNonInteractiveSession: boolean
  enablePromptCaching?: boolean
  skipCacheWrite?: boolean
  effortValue?: EffortValue
  maxOutputTokensOverride?: number
  fallbackModel?: string
  fastMode?: boolean
  advisorModel?: string
  taskBudget?: { total: number; remaining?: number }
  outputFormat?: BetaJSONOutputFormat
  // …其餘 15+ 個欄位
}
```

所有呼叫入口最終都匯聚到私有的 `queryModel()` generator。

---

## 3. 主要公開函式

| 函式 | 說明 |
|---|---|
| `queryModelWithStreaming()` | 包裝 queryModel，以 AsyncGenerator 回傳串流事件 |
| `queryModelWithoutStreaming()` | 迭代 queryModel，取出第一個 AssistantMessage 後回傳 |
| `executeNonStreamingRequest()` | 非串流 fallback helper，用於 streaming 失敗時 |
| `verifyApiKey()` | 以 Haiku 做最小 API 驗證 |
| `getExtraBodyParams()` | 解析 `CLAUDE_CODE_EXTRA_BODY` 環境變數 |
| `getAPIMetadata()` | 組合 user_id（含 device_id、OAuth UUID、session_id） |
| `userMessageToMessageParam()` | 加上 cache_control 標記 |
| `assistantMessageToMessageParam()` | 同上，但排除 thinking / redacted_thinking 區塊 |
| `stripExcessMediaItems()` | 移除超過 100 個媒體項目（API 限制）的最舊項目 |
| `getPromptCachingEnabled()` | 判斷某個 model 是否啟用 prompt caching |

---

## 4. 請求組裝流程（`queryModel` 內部）

```
1. 檢查 off-switch（tengu-off-switch GrowthBook flag，僅對 Opus 生效）
2. 計算 betas = getMergedBetas(model, { isAgenticQuery })
3. Advisor 模型決策（isAdvisorEnabled, isValidAdvisorModel）
4. Tool search 啟用判斷（isToolSearchEnabled）
5. 過濾 filteredTools（移除未發現的 deferred tool）
6. normalizeMessagesForAPI → ensureToolResultPairing → stripAdvisorBlocks → stripExcessMediaItems
7. 計算 fingerprint（fingerprint.ts）
8. 組裝 systemPrompt（attribution header + CLI sys prefix + advisor instructions）
9. buildSystemPromptBlocks（加 cache_control）
10. 構建 paramsFromContext 閉包（每次 retry 重新計算動態 betas）
11. 啟動 withRetry → anthropic.beta.messages.create({ stream: true })
12. 串流消費（for await of stream）
```

---

## 5. `paramsFromContext` 閉包

此閉包在每次 retry 時被呼叫，動態計算最終的 API params：

```typescript
{
  model: normalizeModelStringForAPI(options.model),  // 去除 [1m] 後綴
  messages: addCacheBreakpoints(...),
  system,
  tools: allTools,
  betas: betasParams,           // 動態：含 context-1m / fast-mode / afk-mode 等 latch
  metadata: getAPIMetadata(),
  max_tokens: maxOutputTokens,
  thinking,                     // adaptive 或 { budget_tokens, type: 'enabled' }
  temperature,                  // 僅在 thinking disabled 時設定
  context_management,           // 見 getAPIContextManagement()
  output_config: {              // effort / task_budget / format
    effort?,
    task_budget?,
    format?
  },
  speed?,                       // 'fast' 當 fast mode 啟用
  ...extraBodyParams
}
```

---

## 6. Streaming 回應處理

串流事件處理用 `switch(part.type)` 分派：

| 事件 | 處理 |
|---|---|
| `message_start` | 儲存 partialMessage、usage、research（ant-only） |
| `content_block_start` | 依 type 初始化 contentBlock（tool_use / server_tool_use / text / thinking） |
| `content_block_delta` | 累加 text_delta / thinking_delta / input_json_delta / signature_delta / connector_text_delta |
| `content_block_stop` | 組裝 AssistantMessage，yield 給呼叫方 |
| `message_delta` | 更新 stopReason、usage |
| `message_stop` | 結束串流，觸發成功日誌 |

串流防護機制：
- **Watchdog timer**：`CLAUDE_ENABLE_STREAM_WATCHDOG=1` 啟用，預設 90s 無事件則中止
- **Stall detection**：每個事件後計算間隔，>30s 記錄 `tengu_streaming_stall` event
- **resource cleanup**：`releaseStreamResources()` 確保 TLS socket buffer 被釋放

---

## 7. 非串流 Fallback

當串流失敗時，`executeNonStreamingRequest()` 接管：

```typescript
await anthropic.beta.messages.create(
  { ...adjustedParams, model: normalizeModelStringForAPI(adjustedParams.model) },
  { signal, timeout: fallbackTimeoutMs }  // 預設 300s，CLAUDE_CODE_REMOTE 環境 120s
)
```

`adjustParamsForNonStreaming()` 將 `max_tokens` 限制在 `MAX_NON_STREAMING_TOKENS`。

---

## 8. Prompt Caching 策略

```typescript
// 1h TTL 條件（should1hCacheTTL）：
// - Bedrock 用戶 + ENABLE_PROMPT_CACHING_1H_BEDROCK=1
// - 1P subscriber（非 overage）且 query source 在 GrowthBook allowlist 中

getCacheControl({ scope?, querySource? }) → {
  type: 'ephemeral',
  ttl?: '1h',          // 滿足 should1hCacheTTL
  scope?: 'global'     // 滿足 shouldUseGlobalCacheScope
}
```

快取破壞防護（`PROMPT_CACHE_BREAK_DETECTION` feature flag）：
- 每次請求前記錄 system + tool schemas + betas 等狀態的 hash
- 狀態改變時發送 `tengu_prompt_cache_break` 診斷事件

---

## 9. Beta Header Latch 機制

為避免 session 中途切換 beta header 破壞 server-side prompt cache，採用「sticky-on」latch：

```typescript
// 一旦觸發即設為 true，在 /clear 或 /compact 前不會回頭
afkModeHeaderLatched    // auto mode 首次啟用
fastModeHeaderLatched   // fast mode 首次使用
cacheEditingHeaderLatched  // cached microcompact 首次啟用
thinkingClearLatched    // 距上次 API 呼叫超過 1h（cache TTL）
```

---

## 10. API Limits（`apiLimits.ts`）

| 限制 | 數值 |
|---|---|
| 圖片 base64 最大 | 5 MB |
| PDF 最大原始大小 | 20 MB（base64 後 ~27 MB） |
| PDF 最大頁數（API） | 100 頁 |
| PDF 提取大小門檻 | 3 MB（超過則拆成圖片） |
| PDF 提取最大大小 | 100 MB |
| 單次 Read 最大頁數 | 20 頁 |
| @ mention 內嵌 PDF 門檻 | 10 頁 |
| 每次請求最大媒體數 | 100 |
