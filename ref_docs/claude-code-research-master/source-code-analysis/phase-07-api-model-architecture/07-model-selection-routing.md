# 07 — 模型選擇與路由邏輯

來源：`aliases.ts`、`modelAllowlist.ts`、`validateModel.ts`、`deprecation.ts`、`agent.ts`、`check1mAccess.ts`、`contextWindowUpgradeCheck.ts`

---

## 1. 模型別名系統（aliases.ts）

```typescript
export const MODEL_ALIASES = [
  'sonnet',       // → getDefaultSonnetModel()
  'opus',         // → getDefaultOpusModel()
  'haiku',        // → getDefaultHaikuModel()
  'best',         // → getBestModel() = getDefaultOpusModel()
  'sonnet[1m]',   // → getDefaultSonnetModel() + '[1m]'
  'opus[1m]',     // → getDefaultOpusModel() + '[1m]'
  'opusplan',     // → getDefaultSonnetModel()（plan mode 時切 Opus）
] as const

// 家族別名（用於 allowlist 匹配）
export const MODEL_FAMILY_ALIASES = ['sonnet', 'opus', 'haiku'] as const
```

別名解析規則：
- 別名總是解析到目前最新的預設版本（隨版本更新而改變）
- `[1m]` 後綴可附加於任何別名，如 `haiku[1m]`（即使 Haiku 無 1M 變體）
- `opusplan`：預設解析為 Sonnet，僅在 `permissionMode === 'plan'` 時切換至 Opus

---

## 2. 模型 Allowlist（modelAllowlist.ts）

### 三層匹配邏輯

```typescript
isModelAllowed(model: string): boolean
```

**第一層 — 直接匹配**：
- 模型在 allowlist 中精確出現
- 但若是家族別名且同時有更具體條目（如 `['opus', 'opus-4-5']`），家族別名被忽略

**第二層 — 家族別名匹配**：
- allowlist 含 `opus` → 允許所有 opus 系列模型（萬用字元）
- 但若 allowlist 同時含 `opus-4-5` → `opus` 家族別名降為無效，只允許 opus 4.5

**第三層 — 版本前綴匹配**：
- `opus-4-5` 匹配 `claude-opus-4-5-20251101`（段邊界匹配，不誤匹配 `opus-4-50`）
- `claude-opus-4-5` 也有效（有無 `claude-` 前綴皆可）

### 別名雙向解析

```typescript
// 若輸入是別名，解析後再比對
isModelAllowed('opus') → parseUserSpecifiedModel('opus') = 'claude-opus-4-6' → 查 allowlist

// 若 allowlist 中有別名，解析後與輸入比對
allowlist: ['opus'] → parseUserSpecifiedModel('opus') = 'claude-opus-4-6' → 與 input 比對
```

### 設定範例

```json
// settings.json
{
  "availableModels": ["sonnet", "haiku"]        // 僅 Sonnet 和 Haiku 家族
  "availableModels": ["opus-4-5"]               // 僅 Opus 4.5 具體版本
  "availableModels": ["claude-opus-4-6"]        // 僅 Opus 4.6 完整 ID
  "availableModels": []                          // 封鎖所有用戶指定模型（只能用預設）
}
```

---

## 3. 模型驗證（validateModel.ts）

`validateModel()` 在 `/model` 指令中被呼叫，驗證用戶輸入的模型是否有效：

```typescript
// 步驟：
// 1. 空字串 → 無效
// 2. availableModels 白名單檢查
// 3. MODEL_ALIASES 中 → 直接有效（不需 API 呼叫）
// 4. ANTHROPIC_CUSTOM_MODEL_OPTION 匹配 → 有效（用戶已預驗證）
// 5. 記憶體快取（validModelCache）
// 6. 實際 API 呼叫（sideQuery，max_tokens=1，cache_control=ephemeral）
```

### 錯誤處理

| 錯誤類型 | 訊息 |
|---|---|
| `NotFoundError`（404） | `Model '${model}' not found` + 3P fallback 建議 |
| `AuthenticationError` | 認證失敗提示 |
| `APIConnectionError` | 網路錯誤提示 |
| 其他 `APIError` | `API error: ${message}` |
| 未知錯誤 | `Unable to validate model: ${message}` |

### 3P Fallback 建議鏈

```typescript
// 當 3P provider 無法找到較新版本時，建議降級：
opus-4-6    → opus41（3P fallback）
sonnet-4-6  → sonnet45（3P fallback）
sonnet-4-5  → sonnet40（3P fallback）
```

---

## 4. 模型棄用（deprecation.ts）

```typescript
const DEPRECATED_MODELS = {
  'claude-3-opus': {
    retirementDates: {
      firstParty: 'January 5, 2026',
      bedrock:    'January 15, 2026',
      vertex:     'January 5, 2026',
      foundry:    'January 5, 2026',
    }
  },
  'claude-3-7-sonnet': {
    retirementDates: {
      firstParty: 'February 19, 2026',
      bedrock:    'April 28, 2026',
      vertex:     'May 11, 2026',
      foundry:    'February 19, 2026',
    }
  },
  'claude-3-5-haiku': {
    retirementDates: {
      firstParty: 'February 19, 2026',
      bedrock:    null,    // 尚未棄用
      vertex:     null,
      foundry:    null,
    }
  }
}
```

匹配採用 substring（case-insensitive），棄用日期依 provider 不同。

```typescript
getModelDeprecationWarning(modelId)
// → '⚠ {ModelName} will be retired on {date}. Consider switching to a newer model.'
// → null 若非棄用模型或該 provider 尚未棄用
```

---

## 5. Fast Mode（isFastMode）

Fast mode 判斷在 `queryModel` 中執行：

```typescript
const isFastMode =
  isFastModeEnabled() &&        // feature enabled
  isFastModeAvailable() &&      // not throttled globally
  !isFastModeCooldown() &&      // not in cooldown period
  isFastModeSupportedByModel(options.model) &&  // model supports it
  !!options.fastMode            // caller requested it
```

Fast mode 相關行為：
- `speed: 'fast'` 加入 API 請求
- `FAST_MODE_BETA_HEADER` 使用 latch（sticky-on）以保護 prompt cache
- `/model` 選擇器在 fastMode=true 時顯示定價後綴（getOpus46PricingSuffix）
- Cooldown 期間停止送 `speed='fast'`，但 beta header 仍持續（避免 cache 破壞）

---

## 6. Subagent 模型路由（agent.ts）

### 路由優先順序

```typescript
getAgentModel(agentModel, parentModel, toolSpecifiedModel?, permissionMode?)

// 1. CLAUDE_CODE_SUBAGENT_MODEL 環境變數（最高優先）
// 2. toolSpecifiedModel（工具定義中的 model 屬性）
// 3. agentModel（agent 定義中的 model 屬性）
// 4. 'inherit'（預設，從 parent 繼承）
```

### 家族別名匹配（aliasMatchesParentTier）

```typescript
// 防止無聲降級：若 parent 是 Opus 4.6，subagent 'opus' 應繼承 Opus 4.6
// 而非解析到 3P 可能較舊的 getDefaultOpusModel()
aliasMatchesParentTier('opus', 'claude-opus-4-6[1m]')  → true（繼承 parent 模型）
aliasMatchesParentTier('haiku', 'claude-opus-4-6[1m]') → false（降級，合理）

// 特例：opus[1m]、best、opusplan 不適用此匹配（有額外語義）
```

### Bedrock 地區前綴繼承

```typescript
// Parent: eu.anthropic.claude-opus-4-6-v1
// Agent model: 'sonnet'（別名）
// → 解析為 eu.anthropic.claude-sonnet-4-6（繼承 eu 前綴）

// 若 agent 明確指定帶前綴的模型（如 'us.anthropic.claude-haiku-4-5'）
// → 保留 agent 自訂前綴，不覆蓋（避免意外跨區 IAM 問題）
```

---

## 7. 1M Context 存取控制

### checkOpus1mAccess / checkSonnet1mAccess

```typescript
checkOpus1mAccess(): boolean
// - is1mContextDisabled() → false（DISABLE_1M_CONTEXT=true 全域關閉）
// - isClaudeAISubscriber() → isExtraUsageEnabled()（需 extra usage 開通）
// - 其他（PAYG API 用戶）→ true（直接放行）
```

### isExtraUsageEnabled

依 `cachedExtraUsageDisabledReason` 判斷：
- `null`（無禁用原因）→ 啟用
- `'out_of_credits'` → 仍算啟用（已開通但額度耗盡）
- 其他（`overage_not_provisioned` 等）→ 停用

### isOpus1mMergeEnabled

```typescript
// 控制 UI 是否顯示合併的「Opus (1M context)」選項（而非 Opus + Opus 1M 兩個選項）
function isOpus1mMergeEnabled(): boolean {
  if (is1mContextDisabled())     return false
  if (isProSubscriber())         return false
  if (getAPIProvider() !== 'firstParty') return false
  // subscriber 但 subscriptionType = null（stale OAuth token）→ false（fail closed）
  if (isClaudeAISubscriber() && getSubscriptionType() === null) return false
  return true
}
```

---

## 8. 上下文窗口升級提示（contextWindowUpgradeCheck.ts）

```typescript
getUpgradeMessage('warning')
// → '/model opus[1m]'（當用戶在 'opus' 且有 opus 1M 存取）
// → '/model sonnet[1m]'（當用戶在 'sonnet' 且有 sonnet 1M 存取）

getUpgradeMessage('tip')
// → 'Tip: You have access to Opus 1M with 5x more context'
```

僅在用戶明確設定了 `opus` 或 `sonnet` 別名（非 null 預設）時才顯示升級提示。
