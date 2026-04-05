# 03 — Provider 支援架構

來源：`src/utils/model/providers.ts`、`bedrock.ts`、`modelCapabilities.ts`、`modelSupportOverrides.ts`

---

## 1. Provider 型別與偵測

```typescript
export type APIProvider = 'firstParty' | 'bedrock' | 'vertex' | 'foundry'

export function getAPIProvider(): APIProvider {
  return isEnvTruthy(process.env.CLAUDE_CODE_USE_BEDROCK)   ? 'bedrock'
       : isEnvTruthy(process.env.CLAUDE_CODE_USE_VERTEX)    ? 'vertex'
       : isEnvTruthy(process.env.CLAUDE_CODE_USE_FOUNDRY)   ? 'foundry'
       : 'firstParty'
}
```

Provider 偵測完全依賴環境變數，無 runtime 探測。

---

## 2. First-party（api.anthropic.com）

### 端點驗證

```typescript
isFirstPartyAnthropicBaseUrl(): boolean
// true 若 ANTHROPIC_BASE_URL 未設定（預設）或為 api.anthropic.com
// ant 用戶額外允許 api-staging.anthropic.com
```

### 特性

- 支援所有 beta headers（PROMPT_CACHING_SCOPE、FAST_MODE、AFK_MODE 等）
- 唯一支援 OAuth 認證（`isClaudeAISubscriber()`）
- `shouldIncludeFirstPartyOnlyBetas()` 為 true

---

## 3. AWS Bedrock

### 模型 ID 格式

- **Foundation model**：`anthropic.claude-3-5-sonnet-20241022-v2:0`（無前綴）
- **Cross-region inference profile**：`us.anthropic.claude-opus-4-6-v1`（有地區前綴）
- **Application inference profile ARN**：`arn:aws:bedrock:<region>:<account>:inference-profile/<profile-id>`

### 地區前綴

```typescript
const BEDROCK_REGION_PREFIXES = ['us', 'eu', 'apac', 'global'] as const

getBedrockRegionPrefix('eu.anthropic.claude-sonnet-4-5-20250929-v1:0') // → 'eu'
applyBedrockRegionPrefix('anthropic.claude-sonnet-4-5-v1:0', 'eu')     // → 'eu.anthropic...'
```

Subagent 模型解析時，會繼承 parent model 的地區前綴（避免 IAM 跨區問題）。

### Inference Profile 查詢

```typescript
// memoized（每 session 只查一次）
getBedrockInferenceProfiles()
// 查詢 SYSTEM_DEFINED profiles，過濾 anthropic 模型
// 結果用於 getBedrockModelStrings()，以 firstParty ID 為 needle 做 substring match
```

### Application Inference Profile（ARN 格式）

當 model 包含 `application-inference-profile` 時，`queryModel` 會呼叫：

```typescript
getInferenceProfileBackingModel(profileId)
// → 從 GetInferenceProfileCommand 取得 backing model ARN 的最後一段
// 用於 cost 計算（不影響 API 呼叫的 model 欄位）
```

### Bedrock Beta 限制

Bedrock 只支援少數 beta headers，且必須放在 `extraBodyParams.anthropic_beta` 而非 HTTP header：

```typescript
export const BEDROCK_EXTRA_PARAMS_HEADERS = new Set([
  'interleaved-thinking-2025-05-14',
  'context-1m-2025-08-07',
  'tool-search-tool-2025-10-19',  // Bedrock/Vertex 版的 tool search
])
```

### Bedrock 認證

```typescript
// 優先順序：
// 1. AWS_BEARER_TOKEN_BEDROCK → API key 認證，跳過 AWS credential refresh
// 2. CLAUDE_CODE_SKIP_BEDROCK_AUTH → noAuth（測試用）
// 3. refreshAndGetAwsCredentials() → 讀取 AWS IAM credentials
```

---

## 4. Google Vertex AI

### 模型 ID 格式

`claude-sonnet-4-5@20250929`（`@` 分隔版本日期）

### Vertex Beta 限制

```typescript
export const VERTEX_COUNT_TOKENS_ALLOWED_BETAS = new Set([
  'claude-code-20250219',
  'interleaved-thinking-2025-05-14',
  'context-management-2025-06-27',
])
// countTokens 端點只接受這三個 betas，其他會導致 400
```

### Tool Search Header 差異

1P / Foundry 用 `advanced-tool-use-2025-11-20`，Vertex / Bedrock 用 `tool-search-tool-2025-10-19`。

---

## 5. Azure Foundry

### 模型 ID 格式

`claude-opus-4-6`（無日期後綴），deployment ID 由用戶自定義。

由於 deployment ID 可能與模型名稱無關，`getMarketingNameForModel()` 對 foundry 回傳 `undefined`。

---

## 6. `modelCapabilities.ts` — 動態能力快取（Ant Only）

```typescript
// 條件：USER_TYPE === 'ant' && firstParty && isFirstPartyAnthropicBaseUrl()
refreshModelCapabilities()  // 呼叫 anthropic.models.list()，快取至 ~/.claude/cache/model-capabilities.json

getModelCapability(model)   // 讀快取，回傳 { id, max_input_tokens?, max_tokens? }
```

快取保存時間無限制（無 TTL），每次 `refreshModelCapabilities()` 呼叫時比對 isEqual，只有實際改變才寫磁碟。

---

## 7. `modelSupportOverrides.ts` — 3P 能力覆蓋

3P 用戶可透過環境變數宣告自訂模型的功能支援：

```bash
ANTHROPIC_DEFAULT_OPUS_MODEL=my-opus-deployment
ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES=effort,thinking,adaptive_thinking
```

```typescript
get3PModelCapabilityOverride(model, 'thinking')  // → boolean | undefined
```

支援的 capability 值：`effort` | `max_effort` | `thinking` | `adaptive_thinking` | `interleaved_thinking`

此機制讓第三方部署可宣告自己支援的功能，覆蓋程式碼中對 model ID 的硬編碼判斷。

---

## 8. Provider 對應矩陣

| 功能 | firstParty | bedrock | vertex | foundry |
|---|---|---|---|---|
| Prompt caching（5min） | 是 | 是 | 是 | 是 |
| Prompt caching（1h TTL） | 是（subscriber/ant） | 是（opt-in env） | 否 | 否 |
| Fast mode | 是 | 否 | 否 | 否 |
| AFK mode | 是 | 否 | 否 | 否 |
| Global cache scope | 是（subscriber） | 否 | 否 | 否 |
| Tool search（advanced） | 是 | 否（需 3P header） | 否（需 3P header） | 是 |
| Model capabilities API | 是（ant only） | 否 | 否 | 否 |
