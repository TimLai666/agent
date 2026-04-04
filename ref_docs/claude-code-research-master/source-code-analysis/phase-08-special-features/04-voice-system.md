# 04 — 語音系統分析

## 概覽

語音模式（Voice Mode）讓使用者能用語音與 Claude Code 互動。架構位於 `src/voice/`，僅有一個主要檔案 `voiceModeEnabled.ts`（其餘邏輯散落在 hooks 和 services 中）。

---

## 啟用條件（雙重閘門）

來源：`src/voice/voiceModeEnabled.ts`

### 1. GrowthBook Kill-switch 閘門

```typescript
function isVoiceGrowthBookEnabled(): boolean {
  return feature('VOICE_MODE')
    ? !getFeatureValue_CACHED_MAY_BE_STALE('tengu_amber_quartz_disabled', false)
    : false
}
```

- 編譯期 flag：`feature('VOICE_MODE')`（bun:bundle）
- 運行期 kill-switch：`tengu_amber_quartz_disabled`（GrowthBook）
  - 預設 `false`（未停用），即語音模式預設可用
  - 設為 `true` → 緊急關閉語音模式
  - **正向 ternary 模式**：確保 `VOICE_MODE` 字串字面量不出現在外部 build 中

### 2. OAuth 認證閘門

```typescript
function hasVoiceAuth(): boolean {
  if (!isAnthropicAuthEnabled()) return false
  const tokens = getClaudeAIOAuthTokens()
  return Boolean(tokens?.accessToken)
}
```

**語音模式強制要求 Anthropic OAuth**，以下情況無法使用：
- API Key 認證
- AWS Bedrock
- Google Vertex AI
- Anthropic Foundry

原因：語音模式使用 `voice_stream` endpoint，僅在 `claude.ai` 上可用。

---

## 完整啟用檢查

```typescript
function isVoiceModeEnabled(): boolean {
  return hasVoiceAuth() && isVoiceGrowthBookEnabled()
}
```

---

## Command 設定

來源：`src/commands/voice/index.ts`

```typescript
const voice = {
  type: 'local',
  name: 'voice',
  description: 'Toggle voice mode',
  availability: ['claude-ai'],      // 僅 claude.ai 認證可用
  isEnabled: () => isVoiceGrowthBookEnabled(),  // 顯示條件：GrowthBook 開啟
  get isHidden() {
    return !isVoiceModeEnabled()    // 隱藏條件：未完整啟用（含 OAuth 檢查）
  },
  supportsNonInteractive: false,    // 不支援非互動模式
}
```

`isEnabled`（顯示在選單）與 `isHidden`（是否顯示）分開控制：
- GrowthBook 啟用但無 OAuth → 命令出現在選單，但點擊後提示需要登入
- GrowthBook 停用 → 命令完全不顯示

---

## 語音相關的 Analytics 事件

來源：grep 掃描結果

| 事件名 | 說明 |
|--------|------|
| `tengu_voice_recording_started` | 開始錄音 |
| `tengu_voice_recording_completed` | 錄音完成 |
| `tengu_voice_silent_drop_replay` | 靜音片段丟棄重播 |
| `tengu_voice_stream_early_retry` | 語音串流提前重試 |
| `tengu_voice_toggled` | 語音模式切換 |

---

## 相關元件

透過 grep 確認的相關檔案：

| 檔案 | 功能 |
|------|------|
| `src/hooks/useVoiceIntegration.tsx` | React hook（10 次引用 feature flag） |
| `src/services/voiceStreamSTT.ts` | 語音串流 STT（Speech-to-Text）服務 |
| `src/components/LogoV2/VoiceModeNotice.tsx` | 語音模式提示 UI |
| `src/components/PromptInput/VoiceIndicator.tsx` | 輸入框語音指示器 |

---

## 安全設計

1. **Kill-switch 優先**：`tengu_amber_quartz_disabled` 可遠端緊急停用，無需更新客戶端
2. **認證隔離**：語音功能只走 Anthropic OAuth，與 API Key 流程完全分離
3. **非互動模式禁止**：`supportsNonInteractive: false`，防止腳本濫用語音模式
4. **新安裝默認可用**：kill-switch 預設 `false`，新安裝不需等待 GrowthBook 初始化
