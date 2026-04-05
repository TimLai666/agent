# 01 — 成本追蹤架構全景

## 概述

Claude Code 的成本追蹤系統由兩個核心檔案組成：`cost-tracker.ts`（邏輯層）與 `costHook.ts`（React 生命週期整合層）。兩者共同構成「即時累積 → 持久化 → 恢復」的完整成本狀態管理迴路。

---

## 一、狀態儲存層（bootstrap/state.ts）

所有成本狀態都集中於 `bootstrap/state.ts` 模組，`cost-tracker.ts` 透過以下函式存取：

| 函式 | 說明 |
|------|------|
| `addToTotalCostState(cost, modelUsage, model)` | 累加總成本與各 model usage |
| `getTotalCostUSD()` | 取得本 session 累積 USD 成本 |
| `getTotalInputTokens()` / `getTotalOutputTokens()` | 取得 input/output token 計數 |
| `getTotalCacheReadInputTokens()` / `getTotalCacheCreationInputTokens()` | 快取 token 計數 |
| `getModelUsage()` / `getUsageForModel(model)` | 取得各 model 使用量 |
| `setCostStateForRestore(data)` | 恢復先前儲存的狀態 |
| `resetCostState()` | 清除狀態（用於 session 結束） |

---

## 二、cost-tracker.ts 核心功能分析

### 1. StoredCostState 型別

```typescript
type StoredCostState = {
  totalCostUSD: number
  totalAPIDuration: number
  totalAPIDurationWithoutRetries: number
  totalToolDuration: number
  totalLinesAdded: number
  totalLinesRemoved: number
  lastDuration: number | undefined
  modelUsage: { [modelName: string]: ModelUsage } | undefined
}
```

儲存到 project config 的成本快照，包含所有維度：API 耗時（含/不含重試）、工具耗時、程式碼變更行數、各 model 的 token 使用量。

### 2. Session 持久化流程

**儲存**：`saveCurrentSessionCosts(fpsMetrics?)`
- 寫入 project config：`lastCost`、`lastAPIDuration`、`lastModelUsage` 等 12 個欄位
- 額外儲存 FPS 效能指標（`lastFpsAverage`、`lastFpsLow1Pct`）
- 使用 `lastSessionId` 作為 session 隔離鍵

**讀取**：`getStoredSessionCosts(sessionId)`
- 僅當 `projectConfig.lastSessionId === sessionId` 才返回資料
- 重建 `modelUsage` 時補充 `contextWindow` 與 `maxOutputTokens`

**恢復**：`restoreCostStateForSession(sessionId)`
- 呼叫 `getStoredSessionCosts()` 後再呼叫 `setCostStateForRestore()`
- 返回 boolean 表示是否成功恢復

### 3. addToTotalSessionCost — 每次 API 呼叫後的核心記帳函式

```typescript
export function addToTotalSessionCost(
  cost: number,
  usage: Usage,
  model: string,
): number {
  const modelUsage = addToTotalModelUsage(cost, usage, model)
  addToTotalCostState(cost, modelUsage, model)

  const attrs =
    isFastModeEnabled() && usage.speed === 'fast'
      ? { model, speed: 'fast' }
      : { model }

  getCostCounter()?.add(cost, attrs)
  getTokenCounter()?.add(usage.input_tokens, { ...attrs, type: 'input' })
  // ... cache read/write tokens

  // 遞迴處理 advisor 模型的子成本
  for (const advisorUsage of getAdvisorUsage(usage)) {
    const advisorCost = calculateUSDCost(advisorUsage.model, advisorUsage)
    totalCost += addToTotalSessionCost(advisorCost, advisorUsage, advisorUsage.model)
  }
  return totalCost
}
```

**關鍵設計點：**
- Fast Mode 追蹤：`usage.speed === 'fast'` 時加上 `speed: 'fast'` 屬性到 metrics
- Advisor 子模型遞迴：advisor（輔助模型）的成本也被遞迴累積進總成本
- OpenTelemetry Counter 整合：`getCostCounter()` 與 `getTokenCounter()` 為 OTEL 指標儀器

### 4. formatTotalCost — 終端顯示格式

```typescript
export function formatTotalCost(): string {
  const costDisplay =
    formatCost(getTotalCostUSD()) +
    (hasUnknownModelCost()
      ? ' (costs may be inaccurate due to usage of unknown models)'
      : '')
  // ...
}
```

輸出範例：
```
Total cost:            $0.1234
Total duration (API):  2m 30s
Total duration (wall): 5m 12s
Total code changes:    45 lines added, 12 lines removed
Usage by model:
     claude-sonnet-4-6:  1,234 input, 456 output, 789 cache read, 321 cache write ($0.12)
```

### 5. formatModelUsage — Model 聚合顯示

- 以 canonical short name 為 key 聚合多個同型 model 版本
- 範例：`claude-3-5-sonnet-20241022` 和 `claude-3-5-sonnet-20240620` 歸入同一 bucket

### 6. formatCost — 成本格式化規則

```typescript
function formatCost(cost: number, maxDecimalPlaces: number = 4): string {
  return `$${cost > 0.5 ? round(cost, 100).toFixed(2) : cost.toFixed(maxDecimalPlaces)}`
}
```

- 超過 $0.50：顯示 2 位小數（如 `$1.23`）
- 低於 $0.50：顯示 4 位小數（如 `$0.0034`）

---

## 三、costHook.ts — React 生命週期整合

```typescript
export function useCostSummary(
  getFpsMetrics?: () => FpsMetrics | undefined,
): void {
  useEffect(() => {
    const f = () => {
      if (hasConsoleBillingAccess()) {
        process.stdout.write('\n' + formatTotalCost() + '\n')
      }
      saveCurrentSessionCosts(getFpsMetrics?.())
    }
    process.on('exit', f)
    return () => {
      process.off('exit', f)
    }
  }, [])
}
```

**設計要點：**
1. **exit 事件**：在 process 退出時執行，確保成本在 CLI 關閉前被顯示並持久化
2. **hasConsoleBillingAccess()**：只有 Console 用戶（API key）才顯示成本；Claude.ai 訂閱用戶不顯示
3. **FPS 指標**：同步傳入 FPS 效能指標，與成本一同持久化
4. **cleanup**：React useEffect 返回清理函式，防止重複綁定

---

## 四、完整資料流

```
API Response
    │
    ▼
calculateUSDCost()          ← modelCost.ts（定價查表）
    │
    ▼
addToTotalSessionCost()     ← cost-tracker.ts（核心記帳）
    │
    ├─→ addToTotalCostState()   ← bootstrap/state.ts（記憶體狀態）
    ├─→ getCostCounter().add()  ← OTEL metrics
    └─→ getTokenCounter().add() ← OTEL metrics（分 input/output/cache）

Process exit event
    │
    ▼
useCostSummary (costHook.ts)
    │
    ├─→ formatTotalCost()       → 終端顯示
    └─→ saveCurrentSessionCosts() → project config 持久化
```

---

## 五、ModelUsage 型別結構

```typescript
type ModelUsage = {
  inputTokens: number
  outputTokens: number
  cacheReadInputTokens: number
  cacheCreationInputTokens: number
  webSearchRequests: number
  costUSD: number
  contextWindow: number        // 由 getContextWindowForModel() 填充
  maxOutputTokens: number      // 由 getModelMaxOutputTokens() 填充
}
```

每個 model 獨立維護一份 usage 記錄，context window 資訊在讀取時動態注入。

---

## 六、小結

成本追蹤架構的核心設計原則：

1. **Session 隔離**：以 `sessionId` 作為快照識別鍵，避免跨 session 污染
2. **雙層存儲**：記憶體（`bootstrap/state`）+ 磁碟（project config）
3. **訂閱者差異**：Claude.ai 訂閱用戶不顯示成本（`hasConsoleBillingAccess`）
4. **Advisor 遞迴**：advisor 子模型的成本被正確遞迴累積
5. **Fast Mode 標記**：Opus 4.6 fast mode 會在 OTEL metrics 中打標籤
