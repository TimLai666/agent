# 02 — Rate Limiting 機制

## 概述

Claude Code 的 Rate Limiting 機制以 HTTP response header 為主要資料來源，透過三層架構（資料解析 → 狀態管理 → UI 呈現）實現對訂閱用戶的額度管控與警示。

---

## 一、Rate Limit 型別體系

### QuotaStatus

```typescript
type QuotaStatus = 'allowed' | 'allowed_warning' | 'rejected'
```

三個狀態：
- `allowed`：正常使用中
- `allowed_warning`：接近額度上限，進入警告期
- `rejected`：超過額度，請求被拒絕

### RateLimitType

```typescript
type RateLimitType =
  | 'five_hour'       // 5 小時 session 額度
  | 'seven_day'       // 7 天週期額度
  | 'seven_day_opus'  // 7 天 Opus 專屬額度
  | 'seven_day_sonnet'// 7 天 Sonnet 專屬額度
  | 'overage'         // 超出訂閱、使用 overage 額度
```

### ClaudeAILimits — 核心狀態物件

```typescript
export type ClaudeAILimits = {
  status: QuotaStatus
  unifiedRateLimitFallbackAvailable: boolean  // 可否 fallback 到較便宜模型
  resetsAt?: number          // Unix epoch（秒）
  rateLimitType?: RateLimitType
  utilization?: number       // 0-1 使用率
  overageStatus?: QuotaStatus
  overageResetsAt?: number
  overageDisabledReason?: OverageDisabledReason
  isUsingOverage?: boolean
  surpassedThreshold?: number
}
```

---

## 二、HTTP Header 協定

所有 Rate Limit 資訊都透過以下 response headers 傳遞（前綴 `anthropic-ratelimit-unified-`）：

| Header 欄位 | 說明 |
|------------|------|
| `status` | `allowed` / `allowed_warning` / `rejected` |
| `reset` | Unix epoch 重置時間 |
| `representative-claim` | 主要限制類型（`five_hour` / `seven_day` / ...） |
| `overage-status` | Overage 額度狀態 |
| `overage-reset` | Overage 重置時間 |
| `overage-disabled-reason` | Overage 停用原因 |
| `fallback` | `available` 表示可 fallback |
| `5h-utilization` | 0-1 的 5 小時使用率 |
| `5h-reset` | 5 小時窗口重置時間 |
| `5h-surpassed-threshold` | 已超過的警告門檻值 |
| `7d-utilization` | 0-1 的 7 天使用率 |
| `7d-surpassed-threshold` | 已超過的警告門檻值 |

### RawWindowUtilization

```typescript
type RawWindowUtilization = {
  utilization: number  // 0-1 fraction
  resets_at: number    // unix epoch seconds
}
type RawUtilization = {
  five_hour?: RawWindowUtilization
  seven_day?: RawWindowUtilization
}
```

每次 API response 都更新此原始數值（不同於 `currentLimits.utilization` 只在警告門檻觸發時更新），可供外部 statusline 腳本讀取。

---

## 三、Early Warning（提前警告）機制

### 雙軌偵測策略

**軌道一：Server-based（優先）**

伺服器主動在 header 中放入 `surpassed-threshold` 欄位，客戶端直接讀取：

```typescript
function getHeaderBasedEarlyWarning(
  headers: globalThis.Headers,
  unifiedRateLimitFallbackAvailable: boolean,
): ClaudeAILimits | null {
  for (const [claimAbbrev, rateLimitType] of Object.entries(EARLY_WARNING_CLAIM_MAP)) {
    const surpassedThreshold = headers.get(
      `anthropic-ratelimit-unified-${claimAbbrev}-surpassed-threshold`,
    )
    if (surpassedThreshold !== null) {
      // 返回 allowed_warning 狀態
    }
  }
}
```

**軌道二：Time-relative fallback（備援）**

當伺服器未發送 `surpassed-threshold` header 時，客戶端自行計算「消耗速率是否超過窗口允許的速度」：

```typescript
const EARLY_WARNING_CONFIGS: EarlyWarningConfig[] = [
  {
    rateLimitType: 'five_hour',
    claimAbbrev: '5h',
    windowSeconds: 5 * 60 * 60,
    thresholds: [{ utilization: 0.9, timePct: 0.72 }],
    // 含義：在窗口 72% 的時間點前就消耗了 90% 的額度 → 警告
  },
  {
    rateLimitType: 'seven_day',
    claimAbbrev: '7d',
    windowSeconds: 7 * 24 * 60 * 60,
    thresholds: [
      { utilization: 0.75, timePct: 0.6 },
      { utilization: 0.5, timePct: 0.35 },
      { utilization: 0.25, timePct: 0.15 },
    ],
    // 多個門檻：早期大量消耗的不同嚴重度
  },
]
```

時間進度計算：
```typescript
function computeTimeProgress(resetsAt: number, windowSeconds: number): number {
  const nowSeconds = Date.now() / 1000
  const windowStart = resetsAt - windowSeconds
  const elapsed = nowSeconds - windowStart
  return Math.max(0, Math.min(1, elapsed / windowSeconds))
}
```

---

## 四、狀態機更新流程

### extractQuotaStatusFromHeaders

每次 API 呼叫成功後觸發：

```
API Response Headers
    │
    ▼
shouldProcessRateLimits(isSubscriber) ─→ false: 清除狀態, return
    │
    ▼
processRateLimitHeaders(headers)  ← 可能被 mock 覆蓋
    │
    ▼
extractRawUtilization()  → 更新 rawUtilization
    │
    ▼
computeNewLimitsFromHeaders()
    │
    ├─→ status === 'rejected' + overage 狀態  → isUsingOverage 判斷
    └─→ status allowed 時: getEarlyWarningFromHeaders() 優先觸發
    │
    ▼
isEqual(currentLimits, newLimits) ? skip : emitStatusChange()
```

### extractQuotaStatusFromError

HTTP 429 錯誤時觸發，強制設定 `status: 'rejected'`。

### checkQuotaStatus（前置查詢）

Session 啟動時發送一個 `max_tokens: 1` 的最小請求來獲取當前額度狀態：

```typescript
async function makeTestQuery() {
  const model = getSmallFastModel()  // 使用最便宜的模型
  return anthropic.beta.messages
    .create({
      model, max_tokens: 1,
      messages: [{ role: 'user', content: 'quota' }],
      // ...
    })
    .asResponse()
}
```

非互動模式（`-p`）跳過此前置查詢，等待真正請求的 headers。

---

## 五、OverageDisabledReason — Overage 停用原因枚舉

```typescript
export type OverageDisabledReason =
  | 'overage_not_provisioned'       // 未開通 overage
  | 'org_level_disabled'            // 組織層級已停用
  | 'org_level_disabled_until'      // 組織層級暫時停用（月費上限）
  | 'out_of_credits'                // 餘額不足
  | 'seat_tier_level_disabled'      // 席位層級未開通
  | 'member_level_disabled'         // 個人帳號被停用
  | 'seat_tier_zero_credit_limit'   // 席位層級額度為零
  | 'group_zero_credit_limit'       // 群組額度為零
  | 'member_zero_credit_limit'      // 個人額度為零
  | 'org_service_level_disabled'    // 服務層級停用
  | 'org_service_zero_credit_limit' // 服務層級額度為零
  | 'no_limits_configured'          // 未配置任何額度
  | 'unknown'                       // 未知原因
```

---

## 六、rateLimitMessages.ts — 訊息生成邏輯

### 訊息決策樹

```
getRateLimitMessage(limits, model)
    │
    ├─ isUsingOverage = true
    │   ├─ overageStatus === 'allowed_warning' → { warning: "You're close to your extra usage spending limit" }
    │   └─ 其他 → null
    │
    ├─ status === 'rejected' → { error: getLimitReachedText() }
    │
    └─ status === 'allowed_warning'
        ├─ utilization < 0.7 → null（過濾 stale 資料）
        ├─ Team/Enterprise + hasExtraUsageEnabled + 非 billing 管理者 → null
        └─ 其他 → { warning: getEarlyWarningText() }
```

### 特殊情境：Ant 員工（USER_TYPE=ant）

```typescript
function formatLimitReachedText(limit, resetMessage, _model): string {
  if (process.env.USER_TYPE === 'ant') {
    return `You've hit your ${limit}${resetMessage}. If you have feedback about this limit, post in #briarpatch-cc. You can reset your limits with /reset-limits`
  }
  return `You've hit your ${limit}${resetMessage}`
}
```

內部員工會看到 Slack 頻道和 `/reset-limits` 命令的提示。

### Upsell 文字策略

```typescript
function getWarningUpsellText(rateLimitType): string | null {
  // 5 小時 session 限制
  if (rateLimitType === 'five_hour') {
    if (subscriptionType === 'team' || 'enterprise') {
      if (!hasExtraUsageEnabled && isOverageProvisioningAllowed()) {
        return '/extra-usage to request more'
      }
    }
    if (subscriptionType === 'pro' || 'max') {
      return '/upgrade to keep using Claude Code'
    }
  }
  // 週度限制警告不顯示 upsell
}
```

---

## 七、狀態監聽（Pub/Sub）

```typescript
type StatusChangeListener = (limits: ClaudeAILimits) => void
export const statusListeners: Set<StatusChangeListener> = new Set()

export function emitStatusChange(limits: ClaudeAILimits) {
  currentLimits = limits
  statusListeners.forEach(listener => listener(limits))
  logEvent('tengu_claudeai_limits_status_changed', { status, hoursTillReset })
}
```

React hook `useClaudeAiLimits()` 透過 `statusListeners` 訂閱狀態變化，觸發 UI 重繪。

---

## 八、小結

| 機制 | 設計 |
|------|------|
| 資料來源 | HTTP response headers（`anthropic-ratelimit-unified-*`） |
| 警告觸發 | 伺服器 surpassed-threshold + 客戶端 time-relative fallback 雙軌 |
| 狀態傳播 | Pub/Sub（statusListeners Set） |
| 前置查詢 | session 啟動時 max_tokens:1 的探測請求 |
| Mock 支援 | `shouldProcessMockLimits()` 隔離 Ant 員工測試環境 |
| 快取管理 | `rawUtilization` 每次 API 更新；`currentLimits` 只在狀態變化時更新 |
