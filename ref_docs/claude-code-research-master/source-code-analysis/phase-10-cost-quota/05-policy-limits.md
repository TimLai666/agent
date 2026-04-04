# 05 — Policy Limits 團隊管控機制

## 概述

`policyLimits/` 目錄實現了一套組織層級的功能管控系統，允許 Team/Enterprise 管理員透過 API 動態禁用 Claude Code 的特定功能，客戶端採用「fail open + 背景輪詢 + 持久化快取」的設計確保可用性。

---

## 一、系統定位

Policy Limits 不是成本額度（不控制 token 用量），而是功能開關（控制特定功能是否可用）。

**適用對象：**
- Console 用戶（API key）：全部適用
- OAuth 用戶（Claude.ai）：僅 **Team** 和 **Enterprise** 訂閱者適用

```typescript
export function isPolicyLimitsEligible(): boolean {
  if (getAPIProvider() !== 'firstParty') return false        // 不適用於 Bedrock/Vertex
  if (!isFirstPartyAnthropicBaseUrl()) return false          // 不適用於自訂 base URL

  // Console 用戶（有 API key）直接通過
  try {
    const { key: apiKey } = getAnthropicApiKeyWithSource(...)
    if (apiKey) return true
  } catch { /* continue */ }

  // OAuth 用戶需要：Claude.ai tokens + inference scope + Team/Enterprise 訂閱
  const tokens = getClaudeAIOAuthTokens()
  if (!tokens?.scopes?.includes(CLAUDE_AI_INFERENCE_SCOPE)) return false
  if (tokens.subscriptionType !== 'enterprise' && tokens.subscriptionType !== 'team') return false

  return true
}
```

---

## 二、資料結構（types.ts）

```typescript
export const PolicyLimitsResponseSchema = lazySchema(() =>
  z.object({
    restrictions: z.record(z.string(), z.object({ allowed: z.boolean() })),
  }),
)
```

API 回應格式極簡：

```json
{
  "restrictions": {
    "allow_product_feedback": { "allowed": false },
    "allow_remote_sessions": { "allowed": true }
  }
}
```

設計原則：
- **只包含被限制的 policy**（文件注釋：`Only blocked policies are included. If a policy key is absent, it's allowed.`）
- 實際上實作為「任何 policy key 若不存在 → allowed」

---

## 三、fail open 設計

```typescript
export function isPolicyAllowed(policy: string): boolean {
  const restrictions = getRestrictionsFromCache()
  if (!restrictions) {
    // 特例：essential-traffic-only 模式下，部分 policy fail closed
    if (isEssentialTrafficOnly() && ESSENTIAL_TRAFFIC_DENY_ON_MISS.has(policy)) {
      return false
    }
    return true  // fail open：無法取得 restrictions → 一律允許
  }
  const restriction = restrictions[policy]
  if (!restriction) return true  // 未知 policy → 允許
  return restriction.allowed
}

// 預設 deny 的 policies（僅在 essential-traffic-only 模式下生效）
const ESSENTIAL_TRAFFIC_DENY_ON_MISS = new Set(['allow_product_feedback'])
```

**HIPAA 組織的特殊處理**：`allow_product_feedback` 在 essential-traffic-only 模式下（HIPAA 等高安全等級），即使快取不可用也預設拒絕，防止快取失效時意外啟用遙測功能。

---

## 四、快取策略（三層）

### 層次一：Session 記憶體快取

```typescript
let sessionCache: PolicyLimitsResponse['restrictions'] | null = null
```

Session 期間優先讀取記憶體，避免重複磁碟 IO。

### 層次二：磁碟持久化快取

```typescript
const CACHE_FILENAME = 'policy-limits.json'
// 路徑：~/.claude/policy-limits.json

async function saveCachedRestrictions(restrictions) {
  await writeFile(path, jsonStringify(data, null, 2), {
    encoding: 'utf-8',
    mode: 0o600,  // 只有擁有者可讀寫（安全考量）
  })
}
```

### 層次三：ETag 條件式請求

```typescript
function computeChecksum(restrictions): string {
  const sorted = sortKeysDeep(restrictions)  // 深度排序 key，確保 hash 一致性
  const normalized = jsonStringify(sorted)
  const hash = createHash('sha256').update(normalized).digest('hex')
  return `sha256:${hash}`
}

// 發送請求時使用 If-None-Match header
if (cachedChecksum) {
  headers['If-None-Match'] = `"${cachedChecksum}"`
}

// 304 Not Modified → 繼續使用快取
if (response.status === 304) {
  return { success: true, restrictions: null }  // null 表示快取仍有效
}
```

---

## 五、背景輪詢機制

```typescript
const POLLING_INTERVAL_MS = 60 * 60 * 1000  // 1 小時
const DEFAULT_MAX_RETRIES = 5
const FETCH_TIMEOUT_MS = 10000  // 10 秒

export function startBackgroundPolling(): void {
  pollingIntervalId = setInterval(() => {
    void pollPolicyLimits()
  }, POLLING_INTERVAL_MS)
  pollingIntervalId.unref()  // 不阻止 process 退出

  // 確保 process 退出時停止輪詢
  registerCleanup(async () => stopBackgroundPolling())
}
```

輪詢設計：
- 1 小時間隔（管理員配置變更不需即時生效）
- `unref()` 防止輪詢 interval 阻止 process 正常退出
- 背景輪詢失敗時「不 fail closed」（只記錄 log）

---

## 六、Loading Promise 機制

```typescript
const LOADING_PROMISE_TIMEOUT_MS = 30000  // 30 秒超時

export function initializePolicyLimitsLoadingPromise(): void {
  if (loadingCompletePromise) return

  if (isPolicyLimitsEligible()) {
    loadingCompletePromise = new Promise(resolve => {
      loadingCompleteResolve = resolve
      setTimeout(() => {
        if (loadingCompleteResolve) {
          logForDebugging('Policy limits: Loading promise timed out, resolving anyway')
          loadingCompleteResolve()
          loadingCompleteResolve = null
        }
      }, LOADING_PROMISE_TIMEOUT_MS)
    })
  }
}

export async function waitForPolicyLimitsToLoad(): Promise<void> {
  if (loadingCompletePromise) {
    await loadingCompletePromise
  }
}
```

**用途**：在 CLI 初始化時呼叫 `initializePolicyLimitsLoadingPromise()`，讓需要遵守 policy 的功能可以 await `waitForPolicyLimitsToLoad()` 確保 restrictions 已載入。30 秒超時防止死鎖。

---

## 七、Retry 邏輯

```typescript
async function fetchWithRetry(cachedChecksum?): Promise<PolicyLimitsFetchResult> {
  for (let attempt = 1; attempt <= DEFAULT_MAX_RETRIES + 1; attempt++) {
    const result = await fetchPolicyLimits(cachedChecksum)
    if (result.success) return result
    if (result.skipRetry) return result  // auth error：不重試
    if (attempt > DEFAULT_MAX_RETRIES) return result

    const delayMs = getRetryDelay(attempt)  // 指數退避
    await sleep(delayMs)
  }
}
```

Auth 錯誤（`skipRetry: true`）立即放棄，網路/超時錯誤才重試。

---

## 八、錯誤分類

```typescript
switch (kind) {
  case 'auth':    return { success: false, error: '...', skipRetry: true }
  case 'timeout': return { success: false, error: 'Policy limits request timeout' }
  case 'network': return { success: false, error: 'Cannot connect to server' }
  default:        return { success: false, error: message }
}
```

---

## 九、認證方式雙軌

```typescript
function getAuthHeaders(): { headers: Record<string, string>; error?: string } {
  // 優先嘗試 API key（Console 用戶）
  try {
    const { key: apiKey } = getAnthropicApiKeyWithSource({ skipRetrievingKeyFromApiKeyHelper: true })
    if (apiKey) return { headers: { 'x-api-key': apiKey } }
  } catch { }

  // 退回 OAuth（Claude.ai 用戶）
  const oauthTokens = getClaudeAIOAuthTokens()
  if (oauthTokens?.accessToken) {
    return {
      headers: {
        Authorization: `Bearer ${oauthTokens.accessToken}`,
        'anthropic-beta': OAUTH_BETA_HEADER,
      },
    }
  }
}
```

---

## 十、API 端點與 404 處理

```typescript
function getPolicyLimitsEndpoint(): string {
  return `${getOauthConfig().BASE_API_URL}/api/claude_code/policy_limits`
}

// 404 = 無任何限制（功能未啟用或組織無 policy）
if (response.status === 404) {
  return { success: true, restrictions: {} }
}
```

404 時：
1. 返回空 restrictions（全部允許）
2. 刪除本地快取檔案（清除可能過期的舊限制）

---

## 十一、Auth 狀態變化時的刷新

```typescript
export async function refreshPolicyLimits(): Promise<void> {
  await clearPolicyLimitsCache()  // 清除所有快取
  if (!isPolicyLimitsEligible()) return
  await fetchAndLoadPolicyLimits()
  logForDebugging('Policy limits: Refreshed after auth change')
}
```

登入/登出時觸發，確保 policy 與當前用戶身份一致。

---

## 十二、小結

| 機制 | 設計 |
|------|------|
| 適用範圍 | Team/Enterprise OAuth + 所有 Console API key 用戶 |
| 核心原則 | Fail open（獲取失敗 = 全部允許） |
| 快取層次 | 記憶體 → 磁碟（sha256 ETag） → API |
| 更新頻率 | 啟動時 + 背景每 1 小時輪詢 |
| 特殊情況 | essential-traffic-only 模式下 `allow_product_feedback` fail closed |
| 容錯設計 | 30 秒超時 + 5 次指數退避重試 |
