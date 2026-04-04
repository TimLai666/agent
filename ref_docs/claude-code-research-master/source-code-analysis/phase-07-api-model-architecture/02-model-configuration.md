# 02 — 模型配置系統

來源：`src/utils/model/configs.ts`、`model.ts`、`modelOptions.ts`、`modelStrings.ts`

---

## 1. 配置層次結構

```
configs.ts           ← 最底層：宣告每個模型在各 provider 的實際 ID
  ↓
modelStrings.ts      ← 中間層：依當前 provider 解析成 ModelStrings（provider-specific ID）
  ↓
model.ts             ← 業務層：getMainLoopModel / parseUserSpecifiedModel / 顯示名稱
  ↓
modelOptions.ts      ← UI 層：/model 選擇器的選項清單
```

---

## 2. `configs.ts` — 模型 ID 定義

每個模型宣告為 `ModelConfig` 物件，包含四個 provider 的 ID：

```typescript
export type ModelConfig = Record<APIProvider, ModelName>
// APIProvider = 'firstParty' | 'bedrock' | 'vertex' | 'foundry'
```

### 目前所有已定義模型

| 鍵 | firstParty ID | 備註 |
|---|---|---|
| `haiku35` | `claude-3-5-haiku-20241022` | 已棄用（2026-02-19） |
| `haiku45` | `claude-haiku-4-5-20251001` | 目前預設 Haiku |
| `sonnet35` | `claude-3-5-sonnet-20241022` | |
| `sonnet37` | `claude-3-7-sonnet-20250219` | 已棄用（2026-02-19） |
| `sonnet40` | `claude-sonnet-4-20250514` | |
| `sonnet45` | `claude-sonnet-4-5-20250929` | 3P 預設 Sonnet |
| `sonnet46` | `claude-sonnet-4-6` | 1P 預設 Sonnet（本機所運行版本） |
| `opus40` | `claude-opus-4-20250514` | Legacy，已由 remap 重導至 opus46 |
| `opus41` | `claude-opus-4-1-20250805` | Legacy，已由 remap 重導至 opus46 |
| `opus45` | `claude-opus-4-5-20251101` | |
| `opus46` | `claude-opus-4-6` | 目前預設 Opus |

### 關鍵輔助型別

```typescript
export type CanonicalModelId  // 所有 firstParty ID 的 union type
export const CANONICAL_MODEL_IDS  // runtime 陣列，供測試用
export const CANONICAL_ID_TO_KEY  // Map: firstParty ID → ModelKey（如 'opus46'）
```

---

## 3. `modelStrings.ts` — Provider 字串解析

`getModelStrings()` 是同步函式，回傳目前 provider 下的所有模型 ID：

```typescript
// 非 Bedrock：直接查表
getBuiltinModelStrings('firstParty' | 'vertex' | 'foundry')

// Bedrock：非同步查詢 ListInferenceProfiles，結果存入 STATE.modelStrings
// 查詢期間回傳暫時預設值（fallback）
```

### modelOverrides 覆蓋機制

`settings.json` 可配置 `modelOverrides`，格式為 `{ [canonicalId]: providerSpecificId }`：

```json
{
  "modelOverrides": {
    "claude-opus-4-6": "arn:aws:bedrock:us-east-1::inference-profile/my-opus-profile"
  }
}
```

`applyModelOverrides()` 在每次 `getModelStrings()` 回傳時疊加此覆蓋，使 Bedrock ARN 對應到正確的模型鍵。

---

## 4. `model.ts` — 模型選擇邏輯

### 優先級（由高到低）

```
1. 中途 /model 指令（getMainLoopModelOverride()）
2. --model 啟動旗標
3. ANTHROPIC_MODEL 環境變數
4. settings.json model 欄位
5. 內建預設（getDefaultMainLoopModel()）
```

### 預設模型依用戶類型

```typescript
function getDefaultMainLoopModelSetting() {
  if (USER_TYPE === 'ant')        → antModels config defaultModel 或 opus46[1m]
  if (isMaxSubscriber())          → opus46[1m]（若 opus1mMerge 啟用）
  if (isTeamPremiumSubscriber())  → opus46[1m]
  // else → sonnet46（3P 可能是 sonnet45）
}
```

### parseUserSpecifiedModel — 別名解析

```typescript
parseUserSpecifiedModel('opus')         → getDefaultOpusModel()      // 'claude-opus-4-6'
parseUserSpecifiedModel('sonnet')       → getDefaultSonnetModel()     // 'claude-sonnet-4-6'
parseUserSpecifiedModel('haiku')        → getDefaultHaikuModel()      // 'claude-haiku-4-5-...'
parseUserSpecifiedModel('best')         → getBestModel()              // = getDefaultOpusModel()
parseUserSpecifiedModel('opus[1m]')     → 'claude-opus-4-6[1m]'
parseUserSpecifiedModel('opusplan')     → getDefaultSonnetModel()     // Sonnet 為預設，plan mode 切 Opus
```

### Legacy Opus Remap

```typescript
const LEGACY_OPUS_FIRSTPARTY = [
  'claude-opus-4-20250514',   // opus40
  'claude-opus-4-1-20250805', // opus41
  'claude-opus-4-0',
  'claude-opus-4-1',
]
// 若 provider = firstParty 且未設定 CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP，
// 以上模型自動重導至 getDefaultOpusModel()（目前為 opus46）
```

### [1m] 後綴語義

- `model[1m]` 代表啟用 1M context window
- `normalizeModelStringForAPI()` 在實際 API 呼叫前去除此後綴
- 1M 是否啟用透過 `CONTEXT_1M_BETA_HEADER` 在 betas 陣列中宣告

---

## 5. `modelOptions.ts` — UI 選項

`getModelOptions()` 依用戶類型回傳不同的 `/model` 選擇器選項：

### Ant 用戶

預設選項 + antModels GrowthBook 動態模型 + Opus 1M + Sonnet 46 + Sonnet 1M + Haiku 4.5

### Max / Team Premium

預設（Opus 1M）+ Opus 1M（若 !isOpus1mMergeEnabled）+ Sonnet + Sonnet 1M + Haiku

### Pro / Enterprise / Team Standard

預設（Sonnet）+ Sonnet 1M + Opus 4.6（1M merged or separate） + Haiku

### PAYG 1P

預設（Sonnet）+ Sonnet 1M + Opus 4.6 / Opus 1M + Haiku 4.5

### PAYG 3P

預設（Sonnet 4.5）+ custom Sonnet（或 Sonnet 4.6/1M）+ custom Opus（或 Opus 4.1 / 4.6 / 1M）+ custom Haiku

### filterModelOptionsByAllowlist

若 `settings.availableModels` 有設定，移除不在 allowlist 中的選項（保留 `null` 預設值）。

---

## 6. resolveSkillModelOverride — Skill 模型解析

```typescript
// 防止 skill 的 model: opus 在 1M session 中無聲降級至 200K
resolveSkillModelOverride('opus', 'claude-opus-4-6[1m]')
// → 'opus[1m]'（目標支援 1M，繼承後綴）

resolveSkillModelOverride('haiku', 'claude-opus-4-6[1m]')
// → 'haiku'（Haiku 無 1M，正常降級）
```
