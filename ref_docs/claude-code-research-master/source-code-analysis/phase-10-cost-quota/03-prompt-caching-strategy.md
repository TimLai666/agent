# 03 — Prompt Caching 策略

## 概述

`promptCacheBreakDetection.ts` 是 Claude Code 中最精密的分析模組之一，實現了一套「兩階段偵測 + 原因診斷」的 Prompt Cache Break 追蹤系統，同時在 `claudeAiLimits.ts` 中包含了快取命中最佳化的重要設計。

---

## 一、Prompt Cache 的成本意義

Prompt cache 對成本影響巨大：
- **Cache write（新建快取）**：比標準 input token 貴 25%（$3.75 vs $3 per Mtok for Sonnet）
- **Cache read（快取命中）**：比標準 input token 便宜 90%（$0.30 vs $3 per Mtok for Sonnet）

因此每次「cache break」意味著：
1. 重新寫入快取（貴 25%）
2. 後續第一次呼叫無法從快取讀取（少了 90% 折扣）

一個有效的 100K token 快取命中每次可節省約 $0.27（以 Sonnet 定價計算）。

---

## 二、兩階段偵測架構

### Phase 1：recordPromptState（API 呼叫前）

```typescript
export type PromptStateSnapshot = {
  system: TextBlockParam[]
  toolSchemas: BetaToolUnion[]
  querySource: QuerySource
  model: string
  agentId?: AgentId
  fastMode?: boolean
  globalCacheStrategy?: string
  betas?: readonly string[]
  autoModeActive?: boolean
  isUsingOverage?: boolean
  cachedMCEnabled?: boolean
  effortValue?: string | number
  extraBodyParams?: unknown
}
```

追蹤的所有可能影響快取 key 的因素：
- 系統提示內容（`systemHash`）
- 工具 schema（`toolsHash`）
- cache_control 設定（`cacheControlHash`，獨立 hash 以偵測 scope/TTL 翻轉）
- 模型名稱、Fast mode、Beta headers、effort 等

**巧妙設計：stripCacheControl()**

```typescript
function stripCacheControl(
  items: ReadonlyArray<Record<string, unknown>>,
): unknown[] {
  return items.map(item => {
    if (!('cache_control' in item)) return item
    const { cache_control: _, ...rest } = item
    return rest
  })
}
```

計算 `systemHash` 和 `toolsHash` 時去掉 `cache_control` 欄位，使文字內容的 hash 不受 TTL/scope 設定影響。但同時維護 `cacheControlHash` 專門追蹤 cache_control 本身的變化。

**per-tool hash 最佳化：**

```typescript
// Only compute per-tool hashes when the aggregate changed
const computeToolHashes = () => computePerToolHashes(strippedTools, toolNames)
```

只在工具集整體發生變化時才計算各 tool 的 hash，節省 N 次 jsonStringify 的開銷。

### Phase 2：checkResponseForCacheBreak（API 呼叫後）

```typescript
export async function checkResponseForCacheBreak(
  querySource: QuerySource,
  cacheReadTokens: number,
  cacheCreationTokens: number,
  messages: Message[],
  agentId?: AgentId,
  requestId?: string | null,
): Promise<void>
```

**Cache Break 偵測邏輯：**

```typescript
const tokenDrop = prevCacheRead - cacheReadTokens
if (
  cacheReadTokens >= prevCacheRead * 0.95 ||  // 允許 5% 的正常波動
  tokenDrop < MIN_CACHE_MISS_TOKENS           // 絕對值需超過 2,000 tokens
) {
  state.pendingChanges = null
  return  // 非 break，忽略
}
```

雙重過濾條件：
1. **相對下降** > 5%（`prevCacheRead * 0.95`）
2. **絕對下降** > 2,000 tokens（`MIN_CACHE_MISS_TOKENS`）

---

## 三、原因診斷系統

當偵測到 cache break 後，系統從 Phase 1 儲存的 `pendingChanges` 建構原因說明：

```typescript
const parts: string[] = []
if (changes) {
  if (changes.modelChanged)         parts.push(`model changed (${prev} → ${new})`)
  if (changes.systemPromptChanged)  parts.push(`system prompt changed (+${delta} chars)`)
  if (changes.toolSchemasChanged)   parts.push(`tools changed (+${added}/-${removed} tools)`)
  if (changes.fastModeChanged)      parts.push('fast mode toggled')
  if (changes.globalCacheStrategyChanged) parts.push(`global cache strategy changed`)
  if (changes.betasChanged)         parts.push(`betas changed (+x/-y)`)
  if (changes.autoModeChanged)      parts.push('auto mode toggled')
  if (changes.overageChanged)       parts.push('overage state changed (TTL latched, no flip)')
  if (changes.cachedMCChanged)      parts.push('cached microcompact toggled')
  if (changes.effortChanged)        parts.push(`effort changed`)
  if (changes.extraBodyChanged)     parts.push('extra body params changed')
}
```

**時間因素診斷（TTL 過期偵測）：**

```typescript
const CACHE_TTL_5MIN_MS = 5 * 60 * 1000
export const CACHE_TTL_1HOUR_MS = 60 * 60 * 1000

// 判斷是否因 TTL 過期
if (lastAssistantMsgOver1hAgo) {
  reason = 'possible 1h TTL expiry (prompt unchanged)'
} else if (lastAssistantMsgOver5minAgo) {
  reason = 'possible 5min TTL expiry (prompt unchanged)'
} else if (timeSinceLastAssistantMsg !== null) {
  reason = 'likely server-side (prompt unchanged, <5min gap)'
} else {
  reason = 'unknown cause'
}
```

**BQ 分析結論**（來自程式碼注釋）：
> 當所有客戶端旗標都為 false 且時間間隔未達 TTL 時，約 90% 的 break 是伺服器端的 routing/eviction 問題或 billed/inference 不一致。

---

## 四、Tracking Key 設計

```typescript
const TRACKED_SOURCE_PREFIXES = [
  'repl_main_thread',
  'sdk',
  'agent:custom',
  'agent:default',
  'agent:builtin',
]

function getTrackingKey(querySource: QuerySource, agentId?: AgentId): string | null {
  if (querySource === 'compact') return 'repl_main_thread'  // compact 與主線程共享
  for (const prefix of TRACKED_SOURCE_PREFIXES) {
    if (querySource.startsWith(prefix)) return agentId || querySource
  }
  return null  // 短生命週期的 fork agent 不追蹤
}
```

**設計理由：**
- `compact` 與 `repl_main_thread` 共享快取狀態（相同的 cacheSafeParams）
- 有 `agentId` 的 subagent 用 agentId 作為 key，避免多個同型 agent 互相污染
- `speculation`、`session_memory`、`prompt_suggestion` 等一次性 fork 不追蹤

**容量限制：**

```typescript
const MAX_TRACKED_SOURCES = 10
```

防止大量 subagent 造成記憶體無限增長（每個 entry 儲存 ~300KB 的 diffableContent 字串）。

---

## 五、快取命中最佳化：Overage 狀態鎖定

在 `promptCacheBreakDetection.ts` 的追蹤欄位中有一個重要設計：

```typescript
/** Overage state flip — should NOT break cache anymore
 *  (eligibility is latched session-stable in should1hCacheTTL).
 *  Tracked to verify the fix. */
isUsingOverage: boolean
```

Overage 狀態（從訂閱用量切換到 overage 費用）在 session 開始時被「鎖定」（latch），不再每次 API 呼叫都翻轉，從而避免了 cache break。

---

## 六、快取降級通知

### notifyCacheDeletion

```typescript
export function notifyCacheDeletion(querySource: QuerySource, agentId?: AgentId): void {
  const state = previousStateBySource.get(key)
  if (state) {
    state.cacheDeletionsPending = true
  }
}
```

當 cached microcompact 發送 cache_edits deletions 時，下一次 API 回應的 cache read 降低是**預期行為**，不應被標記為 break。

### notifyCompaction

```typescript
export function notifyCompaction(querySource: QuerySource, agentId?: AgentId): void {
  const state = previousStateBySource.get(key)
  if (state) {
    state.prevCacheReadTokens = null  // 重置基線
  }
}
```

Context compaction 後自然會有較少的 messages，cache read 下降是正常的，重置基線避免誤報。

---

## 七、Diff 檔案輸出（偵錯用）

當偵測到 cache break 時，系統會寫入 diff 檔案（`--debug` 模式可查看）：

```typescript
async function writeCacheBreakDiff(prevContent, newContent): Promise<string> {
  const patch = createPatch('prompt-state', prevContent, newContent, 'before', 'after')
  await writeFile(diffPath, patch)
  return diffPath
}
```

diff 內容結構：
```
Model: claude-sonnet-4-6

=== System Prompt ===
[系統提示文字]

=== Tools (N) ===
tool_name
  description: ...
  input_schema: {...}
```

---

## 八、Analytics 事件

每次偵測到 cache break 時發送 `tengu_prompt_cache_break` 事件，包含：
- 所有變更旗標（systemPromptChanged, toolSchemasChanged, ...）
- Token 數量（prevCacheReadTokens, cacheReadTokens, cacheCreationTokens）
- 時間資訊（timeSinceLastAssistantMsg）
- 工具名稱（sanitized，MCP tools 折疊為 'mcp'）

---

## 九、小結

| 功能 | 實作 |
|------|------|
| 快取 break 偵測 | 兩階段（pre/post call）+ 雙重過濾（相對 5% + 絕對 2K tokens） |
| 原因診斷 | 12 種因素追蹤（model, system, tools, betas, effort...） |
| TTL 過期偵測 | 與最近 assistant message 的時間差對比（5min / 1h TTL） |
| 記憶體保護 | MAX_TRACKED_SOURCES = 10 + 最舊優先淘汰 |
| 誤報防護 | cacheDeletionsPending + compaction 通知重置基線 |
| Overage 最佳化 | session 啟動時鎖定 overage 狀態，避免 cache key 翻轉 |
