# 06 — Model Selection 與成本關係

## 概述

Claude Code 的模型選擇策略直接決定每次 API 呼叫的成本。`configs.ts` 定義了跨平台模型 ID 映射，`modelCost.ts` 定義了定價表，而 fast mode 在 Opus 4.6 上引入了截然不同的計費層次。

---

## 一、模型配置架構（configs.ts）

### ModelConfig 型別

```typescript
export type ModelConfig = Record<APIProvider, ModelName>
// APIProvider: 'firstParty' | 'bedrock' | 'vertex' | 'foundry'
```

每個模型在 4 個平台各有不同的 ID：

```typescript
export const CLAUDE_SONNET_4_6_CONFIG = {
  firstParty: 'claude-sonnet-4-6',
  bedrock: 'us.anthropic.claude-sonnet-4-6',
  vertex: 'claude-sonnet-4-6',
  foundry: 'claude-sonnet-4-6',
} as const satisfies ModelConfig
```

### 完整模型目錄（ALL_MODEL_CONFIGS）

```typescript
export const ALL_MODEL_CONFIGS = {
  haiku35:  CLAUDE_3_5_HAIKU_CONFIG,
  haiku45:  CLAUDE_HAIKU_4_5_CONFIG,
  sonnet35: CLAUDE_3_5_V2_SONNET_CONFIG,
  sonnet37: CLAUDE_3_7_SONNET_CONFIG,
  sonnet40: CLAUDE_SONNET_4_CONFIG,
  sonnet45: CLAUDE_SONNET_4_5_CONFIG,
  sonnet46: CLAUDE_SONNET_4_6_CONFIG,
  opus40:   CLAUDE_OPUS_4_CONFIG,
  opus41:   CLAUDE_OPUS_4_1_CONFIG,
  opus45:   CLAUDE_OPUS_4_5_CONFIG,
  opus46:   CLAUDE_OPUS_4_6_CONFIG,
} as const
```

目前支援 11 個模型版本，覆蓋 3 個家族（Haiku / Sonnet / Opus）。

---

## 二、定價體系（modelCost.ts）

### 定價層次

| 定價層 | 常數名稱 | Input | Output | Cache Write | Cache Read |
|--------|----------|-------|--------|-------------|------------|
| Haiku 3.5 | `COST_HAIKU_35` | $0.80 | $4 | $1 | $0.08 |
| Haiku 4.5 | `COST_HAIKU_45` | $1 | $5 | $1.25 | $0.10 |
| Sonnet 系列 | `COST_TIER_3_15` | $3 | $15 | $3.75 | $0.30 |
| Opus 4.5 / 4.6 (normal) | `COST_TIER_5_25` | $5 | $25 | $6.25 | $0.50 |
| Opus 4 / 4.1 | `COST_TIER_15_75` | $15 | $75 | $18.75 | $1.50 |
| Opus 4.6 Fast Mode | `COST_TIER_30_150` | $30 | $150 | $37.50 | $3.00 |

（單位：USD per million tokens）

### 定價映射

```typescript
export const MODEL_COSTS: Record<ModelShortName, ModelCosts> = {
  'haiku-3-5':    COST_HAIKU_35,
  'haiku-4-5':    COST_HAIKU_45,
  'sonnet-3-5':   COST_TIER_3_15,
  'sonnet-3-7':   COST_TIER_3_15,
  'sonnet-4':     COST_TIER_3_15,
  'sonnet-4-5':   COST_TIER_3_15,
  'sonnet-4-6':   COST_TIER_3_15,
  'opus-4':       COST_TIER_15_75,
  'opus-4-1':     COST_TIER_15_75,
  'opus-4-5':     COST_TIER_5_25,
  'opus-4-6':     COST_TIER_5_25,   // Normal mode，fast mode 另外判斷
}
```

---

## 三、成本計算函式

### calculateUSDCost

```typescript
export function calculateUSDCost(resolvedModel: string, usage: Usage): number {
  const modelCosts = getModelCosts(resolvedModel, usage)
  return tokensToUSDCost(modelCosts, usage)
}
```

### tokensToUSDCost

```typescript
function tokensToUSDCost(modelCosts: ModelCosts, usage: Usage): number {
  return (
    (usage.input_tokens / 1_000_000) * modelCosts.inputTokens +
    (usage.output_tokens / 1_000_000) * modelCosts.outputTokens +
    ((usage.cache_read_input_tokens ?? 0) / 1_000_000) * modelCosts.promptCacheReadTokens +
    ((usage.cache_creation_input_tokens ?? 0) / 1_000_000) * modelCosts.promptCacheWriteTokens +
    (usage.server_tool_use?.web_search_requests ?? 0) * modelCosts.webSearchRequests
  )
}
```

5 個計費維度：
1. Input tokens
2. Output tokens
3. Cache read tokens（命中快取，折扣）
4. Cache creation tokens（建立快取，溢價）
5. Web search requests（固定 $0.01/次）

---

## 四、Fast Mode 與 Opus 4.6 特殊計費

### Fast Mode 成本翻倍機制

```typescript
export function getOpus46CostTier(fastMode: boolean): ModelCosts {
  if (isFastModeEnabled() && fastMode) {
    return COST_TIER_30_150  // Fast: $30/$150 per Mtok
  }
  return COST_TIER_5_25      // Normal: $5/$25 per Mtok
}

export function getModelCosts(model: string, usage: Usage): ModelCosts {
  const shortName = getCanonicalName(model)
  if (shortName === 'opus-4-6') {
    const isFastMode = usage.speed === 'fast'  // API 回傳的 speed 欄位
    return getOpus46CostTier(isFastMode)
  }
  // ...
}
```

Opus 4.6 在 fast mode 下的成本比 normal mode 高 **6 倍**（$30/$150 vs $5/$25）。

**`usage.speed === 'fast'`**：這個欄位由 API response 的 `usage` 物件提供，代表本次請求確實使用了 fast mode 執行。

---

## 五、模型選擇對成本的實際影響（對比）

以 1M input + 100K output token 的任務為例：

| 模型 | Input 成本 | Output 成本 | 合計 |
|------|-----------|------------|------|
| Haiku 3.5 | $0.80 | $0.40 | **$1.20** |
| Haiku 4.5 | $1.00 | $0.50 | **$1.50** |
| Sonnet 4.6 | $3.00 | $1.50 | **$4.50** |
| Opus 4.5/4.6 Normal | $5.00 | $2.50 | **$7.50** |
| Opus 4/4.1 | $15.00 | $7.50 | **$22.50** |
| Opus 4.6 Fast | $30.00 | $15.00 | **$45.00** |

**差距高達 37.5 倍**（Haiku 3.5 vs Opus 4.6 Fast）。

---

## 六、未知模型處理

```typescript
function trackUnknownModelCost(model: string, shortName: ModelShortName): void {
  logEvent('tengu_unknown_model_cost', { model, shortName })
  setHasUnknownModelCost()
}

// Fallback 到當前主模型的定價
return (
  MODEL_COSTS[getCanonicalName(getDefaultMainLoopModelSetting())] ??
  DEFAULT_UNKNOWN_MODEL_COST  // COST_TIER_5_25
)
```

遭遇未知模型時：
1. 發送 analytics 事件
2. 設定 `hasUnknownModelCost` 旗標（會在成本顯示加警告）
3. Fallback 到主模型定價，若主模型也不認識則用 `COST_TIER_5_25`（$5/$25）

---

## 七、modelCapabilities.ts — 動態模型能力快取

```typescript
// 僅 Ant 員工可用（process.env.USER_TYPE === 'ant'）
function isModelCapabilitiesEligible(): boolean {
  if (process.env.USER_TYPE !== 'ant') return false
  if (getAPIProvider() !== 'firstParty') return false
  if (!isFirstPartyAnthropicBaseUrl()) return false
  return true
}
```

`modelCapabilities.ts` 從 API 拉取模型清單，記錄 `max_input_tokens` 和 `max_tokens`，儲存至 `~/.claude/cache/model-capabilities.json`。

**目前僅限 Ant 員工**，功能尚未對外開放（issue #13240 規劃動態 limits 獲取）。

讀取時的 model 比對邏輯：
```typescript
// 優先精確匹配，其次子字串匹配（longest-id-first 排序）
const exact = cached.find(c => c.id.toLowerCase() === m)
if (exact) return exact
return cached.find(c => m.includes(c.id.toLowerCase()))
```

---

## 八、getModelPricingString — 定價字串格式化

```typescript
export function formatModelPricing(costs: ModelCosts): string {
  return `${formatPrice(costs.inputTokens)}/${formatPrice(costs.outputTokens)} per Mtok`
  // 例：$3/$15 per Mtok（Sonnet）
  //     $0.80/$4 per Mtok（Haiku 3.5）
}
```

---

## 九、Web Search 計費

```typescript
// 固定費率（不依 model 變化）
webSearchRequests: 0.01  // $0.01 per request = $10 per 1000 requests
```

所有模型的 web search 費率相同，計費在 `usage.server_tool_use.web_search_requests` 中報告。

---

## 十、小結

| 面向 | 設計 |
|------|------|
| 模型 ID 管理 | 4 平台統一配置（`configs.ts`） |
| 定價基礎 | 6 個定價層次，最大差距 37.5 倍 |
| Fast Mode 特殊計費 | Opus 4.6 fast mode = 6x normal 成本，依 `usage.speed` 判斷 |
| 未知模型處理 | Fallback + analytics 事件 + 使用者警告 |
| 動態能力 | 目前僅 Ant 員工可用，規劃中（issue #13240） |
| Cache 折扣 | Cache read = 10% of input 成本，是最顯著的成本節約手段 |
