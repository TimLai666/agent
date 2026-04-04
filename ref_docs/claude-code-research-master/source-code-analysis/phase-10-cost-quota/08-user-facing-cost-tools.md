# 08 — 使用者端成本工具

## 概述

Claude Code 提供三個面向使用者的成本/用量相關命令：`/cost`（session 成本）、`/usage`（訂閱額度）、`/stats`（使用統計）。三者定位不同，服務不同的資訊需求。

---

## 一、/cost 命令

### 命令定義（commands/cost/index.ts）

```typescript
const cost = {
  type: 'local',
  name: 'cost',
  description: 'Show the total cost and duration of the current session',
  get isHidden() {
    // Ant 員工即使是訂閱者也能看到成本
    if (process.env.USER_TYPE === 'ant') return false
    return isClaudeAISubscriber()  // 訂閱用戶隱藏此命令
  },
  supportsNonInteractive: true,  // -p 模式可用
  load: () => import('./cost.js'),  // 懶加載
}
```

**隱藏邏輯**：Claude.ai 訂閱用戶的成本由訂閱費涵蓋，不顯示 token 費用；Console API key 用戶按量計費，需要看到成本。Ant 員工即使使用訂閱也能看到（有額外的 `[ANT-ONLY]` 顯示）。

### 實作邏輯（commands/cost/cost.ts）

```typescript
export const call: LocalCommandCall = async () => {
  if (isClaudeAISubscriber()) {
    let value: string

    if (currentLimits.isUsingOverage) {
      value = 'You are currently using your overages to power your Claude Code usage. We will automatically switch you back to your subscription rate limits when they reset'
    } else {
      value = 'You are currently using your subscription to power your Claude Code usage'
    }

    if (process.env.USER_TYPE === 'ant') {
      value += `\n\n[ANT-ONLY] Showing cost anyway:\n ${formatTotalCost()}`
    }
    return { type: 'text', value }
  }
  return { type: 'text', value: formatTotalCost() }
}
```

**四種情境的輸出：**

| 用戶類型 | 狀態 | 輸出 |
|---------|------|------|
| Console（API key）| 任何 | `formatTotalCost()` 完整輸出 |
| 訂閱用戶 | Normal | 訂閱說明文字 |
| 訂閱用戶 | Using Overage | Overage 說明文字 |
| Ant 員工（訂閱） | 任何 | 訂閱文字 + `[ANT-ONLY]` 成本 |

**`formatTotalCost()` 輸出範例：**

```
Total cost:            $0.1234
Total duration (API):  2m 30s
Total duration (wall): 5m 12s
Total code changes:    45 lines added, 12 lines removed
Usage by model:
     claude-sonnet-4-6:  1,234 input, 456 output, 789 cache read, 321 cache write ($0.0923)
      claude-haiku-4-5:  234 input, 45 output, 0 cache read, 0 cache write ($0.0311)
```

---

## 二、/usage 命令

### 命令定義（commands/usage/index.ts）

```typescript
export default {
  type: 'local-jsx',
  name: 'usage',
  description: 'Show plan usage limits',
  availability: ['claude-ai'],  // 僅 Claude.ai 訂閱用戶可用
  load: () => import('./usage.js'),
}
```

`availability: ['claude-ai']` 限制此命令僅對 Claude.ai OAuth 用戶顯示。

### 實作（commands/usage/usage.tsx）

```typescript
export const call: LocalJSXCommandCall = async (onDone, context) => {
  return <Settings onClose={onDone} context={context} defaultTab="Usage" />
}
```

開啟 Settings 面板的 "Usage" 分頁。

### Usage.tsx 元件分析

**fetchUtilization API 呼叫：**

```typescript
export async function fetchUtilization(): Promise<Utilization | null> {
  if (!isClaudeAISubscriber() || !hasProfileScope()) return {}

  // 過期 token 不發請求
  if (tokens && isOAuthTokenExpired(tokens.expiresAt)) return null

  const response = await axios.get<Utilization>(
    `${getOauthConfig().BASE_API_URL}/api/oauth/usage`,
    { headers, timeout: 5000 }
  )
  return response.data
}

export type Utilization = {
  five_hour?: RateLimit | null
  seven_day?: RateLimit | null
  seven_day_oauth_apps?: RateLimit | null
  seven_day_opus?: RateLimit | null
  seven_day_sonnet?: RateLimit | null
  extra_usage?: ExtraUsage | null
}

export type RateLimit = {
  utilization: number | null  // 0-100 百分比
  resets_at: string | null    // ISO 8601
}

export type ExtraUsage = {
  is_enabled: boolean
  monthly_limit: number | null   // 本月額度上限（USD）
  used_credits: number | null    // 已用額度（USD）
  utilization: number | null     // 0-100 百分比
}
```

**LimitBar 元件**：使用 ProgressBar 視覺化各限制的使用率：

```typescript
function LimitBar({ title, limit, maxWidth, showTimeInReset, extraSubtext }) {
  const { utilization, resets_at } = limit
  if (utilization === null) return null

  const usedText = `${Math.floor(utilization)}% used`
  // ...
  return (
    <Box flexDirection="column">
      <Text bold>{title}</Text>
      <ProgressBar ratio={utilization / 100} width={50}
        fillColor="rate_limit_fill" emptyColor="rate_limit_empty" />
      <Text>{usedText}</Text>
      <Text dimColor>Resets {formatResetText(resets_at)}</Text>
    </Box>
  )
}
```

**顯示的額度維度：**
- 5 小時 session 限制
- 7 天週度限制
- 7 天 OAuth Apps 限制
- 7 天 Opus 專屬限制
- 7 天 Sonnet 專屬限制
- Extra Usage（overage）月度額度

---

## 三、/stats 命令

### 命令定義（commands/stats/index.ts）

```typescript
const stats = {
  type: 'local-jsx',
  name: 'stats',
  description: 'Show your Claude Code usage statistics and activity',
  load: () => import('./stats.js'),
}
```

無 `availability` 限制，所有用戶均可使用。

### 實作（commands/stats/stats.tsx）

```typescript
export const call: LocalJSXCommandCall = async onDone => {
  return <Stats onClose={onDone} />
}
```

### Stats 元件功能

```typescript
// 三個時間範圍
const DATE_RANGE_LABELS: Record<StatsDateRange, string> = {
  '7d':  'Last 7 days',
  '30d': 'Last 30 days',
  'all': 'All time',
}

// 使用 aggregateClaudeCodeStatsForRange() 從本地 session 記錄計算
function createAllTimeStatsPromise(): Promise<StatsResult> {
  return aggregateClaudeCodeStatsForRange('all').then(...)
}
```

Stats 元件特性（從 import 可推斷）：
- **asciichart**：繪製 ASCII 折線圖（token 使用趨勢）
- **generateHeatmap**：GitHub 風格的活躍度熱力圖
- **aggregateClaudeCodeStatsForRange**：從本地 JSONL session 記錄聚合統計
- 支援 Tab 切換、鍵盤導航（j/k/arrow）
- 支援截圖複製（`copyAnsiToClipboard`）

**資料來源**：完全本地，從 `~/.claude/projects/*/` 下的 session 記錄計算，不需要 API 呼叫。

---

## 四、三個命令的定位對比

| 命令 | 定位 | 資料來源 | 適用用戶 |
|------|------|----------|---------|
| `/cost` | 本 session 的即時成本 | 記憶體（`getTotalCostUSD()`） | Console 用戶（API key）|
| `/usage` | 訂閱額度的剩餘量 | API（`/api/oauth/usage`）| Claude.ai 訂閱用戶 |
| `/stats` | 歷史使用統計（視覺化） | 本地 session 記錄 | 所有用戶 |

---

## 五、Session 結束時的自動成本顯示

除了手動輸入命令，`costHook.ts` 的 `useCostSummary` 在 process exit 時自動顯示成本：

```typescript
export function useCostSummary(getFpsMetrics?: () => FpsMetrics): void {
  useEffect(() => {
    const f = () => {
      if (hasConsoleBillingAccess()) {
        process.stdout.write('\n' + formatTotalCost() + '\n')
      }
      saveCurrentSessionCosts(getFpsMetrics?.())
    }
    process.on('exit', f)
    return () => process.off('exit', f)
  }, [])
}
```

**`hasConsoleBillingAccess()`**：與 `/cost` 命令的條件相同，只有 Console（API key）用戶才在退出時自動顯示成本摘要。

---

## 六、/usage 的 Mock 支援

`services/api/usage.ts` 中的 `fetchUtilization` 需要有效的 OAuth token，在開發環境中透過 mock limits 系統（`mockRateLimits.ts`）可模擬各種額度狀態。

---

## 七、formatCost 格式規則

```typescript
function formatCost(cost: number, maxDecimalPlaces: number = 4): string {
  return `$${cost > 0.5 ? round(cost, 100).toFixed(2) : cost.toFixed(maxDecimalPlaces)}`
}
```

Usage.tsx 也引用了 `formatCost`（from `src/cost-tracker.js`）來顯示 extra usage 的已用金額。

---

## 八、小結

| 命令 | 類型 | 可用性 | 資料來源 | 主要功能 |
|------|------|--------|----------|---------|
| `/cost` | `local` | Console + Ant | 記憶體 | session 成本 + token breakdown |
| `/usage` | `local-jsx` | Claude.ai only | `/api/oauth/usage` | 訂閱額度 progress bars |
| `/stats` | `local-jsx` | 全部 | 本地 JSONL | 歷史統計 + 熱力圖 + 折線圖 |

三個工具形成完整的成本可見性鏈：即時成本（/cost）→ 額度狀態（/usage）→ 長期趨勢（/stats）。
