# 04 — Token Estimation 預估邏輯

## 概述

`tokenEstimation.ts` 提供三種層次的 token 計數策略，從精確（API 實際計數）到快速估算（字元比例換算），按需選擇適當的精準度與成本。

---

## 一、三種計數策略

### 策略一：API 直接計數（最精確）

**`countTokensWithAPI(content: string)`**

發送到 API 的 `countTokens` 端點取得精確值：

```typescript
export async function countTokensWithAPI(content: string): Promise<number | null> {
  if (!content) return 0
  const message: BetaMessageParam = { role: 'user', content }
  return countMessagesTokensWithAPI([message], [])
}
```

**`countMessagesTokensWithAPI(messages, tools)`**

支援三種 API Provider：
1. **firstParty（Anthropic）**：直接呼叫 `anthropic.beta.messages.countTokens()`
2. **Vertex**：過濾 beta headers（只保留 `VERTEX_COUNT_TOKENS_ALLOWED_BETAS` 中的）
3. **Bedrock**：走獨立的 `countTokensWithBedrock()` 路徑

Thinking block 支援：
```typescript
const containsThinking = hasThinkingBlocks(messages)
if (containsThinking) {
  // API 限制：max_tokens 必須大於 thinking.budget_tokens
  const TOKEN_COUNT_THINKING_BUDGET = 1024
  const TOKEN_COUNT_MAX_TOKENS = 2048
  // ...
}
```

**Vertex beta 過濾原因**：某些 beta（如 web-search）在 Vertex 特定端點會造成 400 錯誤（issue #10789）。

---

### 策略二：Haiku Fallback 計數（近似精確）

**`countTokensViaHaikuFallback(messages, tools)`**

透過讓 Haiku 實際處理（`max_tokens: 1`）來獲取 input token 計數，適用於 API 無法直接 countTokens 的情況：

```typescript
// 模型選擇邏輯（從最便宜的 Haiku 優先，特殊情況升級）
const model =
  isVertexGlobalEndpoint || isBedrockWithThinking || isVertexWithThinking
    ? getDefaultSonnetModel()  // Haiku 不支援時改用 Sonnet
    : getSmallFastModel()      // 通常為 Haiku
```

模型降級原因：
| 情況 | 原因 | 升級到 |
|------|------|-------|
| Vertex global endpoint | Haiku 在全球端點不可用 | Sonnet |
| Bedrock + thinking blocks | Haiku 3.5 不支援 thinking | Sonnet |
| Vertex + thinking blocks | Haiku 3.5 不支援 thinking | Sonnet |

Token 計數公式：
```typescript
const inputTokens = usage.input_tokens
const cacheCreationTokens = usage.cache_creation_input_tokens || 0
const cacheReadTokens = usage.cache_read_input_tokens || 0
return inputTokens + cacheCreationTokens + cacheReadTokens
```

包含 cache tokens，因為這些都是「已處理的輸入」。

**工具搜尋欄位清洗**：

```typescript
function stripToolSearchFieldsFromMessages(messages) {
  // 移除 tool_use blocks 的 'caller' 欄位
  // 移除 tool_result content 的 'tool_reference' blocks
}
```

這些欄位僅在 tool search beta 下有效，計數時必須移除以避免 API 錯誤。

---

### 策略三：粗略估算（最快速）

**`roughTokenCountEstimation(content, bytesPerToken = 4)`**

```typescript
export function roughTokenCountEstimation(
  content: string,
  bytesPerToken: number = 4,
): number {
  return Math.round(content.length / bytesPerToken)
}
```

預設 4 bytes/token 是對英文文字的合理估計。

**檔案類型感知的估算**：

```typescript
export function bytesPerTokenForFileType(fileExtension: string): number {
  switch (fileExtension) {
    case 'json':
    case 'jsonl':
    case 'jsonc':
      return 2  // JSON 有大量單字元符號（{, }, :, ,, "）
    default:
      return 4
  }
}
```

JSON 文件使用 2 bytes/token，因為大量的單字元標點符號每個就是一個 token。

---

## 二、Content Block 型別分別處理

`roughTokenCountEstimationForBlock()` 針對不同 content block 類型有不同策略：

```typescript
function roughTokenCountEstimationForBlock(block): number {
  if (block.type === 'text')
    return roughTokenCountEstimation(block.text)

  if (block.type === 'image' || block.type === 'document')
    return 2000  // 固定估算值
    // 圖片：tokens = (width × height) / 750，最大 2000×2000 = 5333 tokens
    // PDF：避免 base64 展開（1MB PDF → ~325K 估算 vs 實際 ~2000 tokens）

  if (block.type === 'tool_result')
    return roughTokenCountEstimationForContent(block.content)

  if (block.type === 'tool_use')
    return roughTokenCountEstimation(block.name + jsonStringify(block.input ?? {}))

  if (block.type === 'thinking')
    return roughTokenCountEstimation(block.thinking)

  if (block.type === 'redacted_thinking')
    return roughTokenCountEstimation(block.data)

  // server_tool_use, web_search_tool_result, mcp_tool_use 等
  return roughTokenCountEstimation(jsonStringify(block))
}
```

**圖片和 PDF 固定估算 2000 tokens 的原因**：
- 避免將 base64 字串的長度誤算為 token 數（1MB PDF base64 → ~1.33M 字元 → ~333K 估算 tokens vs 實際 ~2000）
- 與 microCompact 的 `IMAGE_MAX_TOKEN_SIZE` 保持一致，避免過早觸發 auto-compact

---

## 三、Bedrock 計數實作

```typescript
async function countTokensWithBedrock({ model, messages, tools, betas, containsThinking }) {
  const client = await createBedrockRuntimeClient()

  // Bedrock CountTokens 需要 foundation model ID（非 inference profile ARN）
  const modelId = isFoundationModel(model)
    ? model
    : await getInferenceProfileBackingModel(model)

  const requestBody = {
    anthropic_version: 'bedrock-2023-05-31',
    messages: messages.length > 0 ? messages : [{ role: 'user', content: 'foo' }],
    max_tokens: containsThinking ? TOKEN_COUNT_MAX_TOKENS : 1,
    // ...
  }

  const { CountTokensCommand } = await import('@aws-sdk/client-bedrock-runtime')
  // AWS SDK 動態 import（defer ~279KB 到實際需要 Bedrock 時）
}
```

AWS SDK 動態載入是刻意的，避免非 Bedrock 用戶承擔 ~279KB 的冷啟動成本。

---

## 四、訊息列表估算

**`roughTokenCountEstimationForMessages(messages)`**

```typescript
export function roughTokenCountEstimationForMessages(messages) {
  let totalTokens = 0
  for (const message of messages) {
    totalTokens += roughTokenCountEstimationForMessage(message)
  }
  return totalTokens
}
```

處理三種訊息類型：
- `type === 'assistant'` / `'user'`：使用 `message.message.content`
- `type === 'attachment'`：透過 `normalizeAttachmentForAPI()` 展開後計算

---

## 五、策略選擇指南

| 情境 | 推薦策略 | 原因 |
|------|----------|------|
| 判斷是否需要 compaction | `countMessagesTokensWithAPI` | 需要精確值 |
| 工具結果截斷判斷 | `roughTokenCountEstimationForFileType` | 速度優先 |
| Token count fallback（Bedrock API 不支援） | `countTokensViaHaikuFallback` | 近似精確 |
| 快速 UI 顯示估算 | `roughTokenCountEstimation` | 即時響應 |
| Compaction 前後 token 變化評估 | `countMessagesTokensWithAPI` | 精確決策 |

---

## 六、hasThinkingBlocks 偵測

```typescript
function hasThinkingBlocks(messages): boolean {
  for (const message of messages) {
    if (message.role === 'assistant' && Array.isArray(message.content)) {
      for (const block of message.content) {
        if (block.type === 'thinking' || block.type === 'redacted_thinking') {
          return true
        }
      }
    }
  }
  return false
}
```

只在 assistant 訊息中檢查，因為 thinking blocks 只出現在 assistant 回應中。`redacted_thinking` 是 extended thinking 的隱藏版本（模型推理內容被服務端隱藏）。

---

## 七、VCR 整合

```typescript
return withTokenCountVCR(messages, tools, async () => {
  // 實際計數邏輯
})
```

`withTokenCountVCR` 允許在測試中錄製/重播 token count API 呼叫，避免測試時真正觸發 API 請求。

---

## 八、小結

| 策略 | 精確度 | 速度 | 成本 | 適用場景 |
|------|--------|------|------|----------|
| `countTokens` API | 最高 | 慢（網路請求） | 有（API 計費） | compaction 決策 |
| Haiku fallback | 高 | 慢（網路請求） | 低（Haiku 計費） | Bedrock/無法直接 countTokens |
| 粗略估算 | 低 | 極快（純計算） | 零 | 工具結果截斷、UI 顯示 |
