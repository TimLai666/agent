# 07 — 隱藏/特殊 Commands 分析

## 概覽

以下是 `src/commands/` 目錄中發現的非標準或特殊功能命令，包含彩蛋、實驗性功能和平台整合命令。

---

## 完全隱藏的 Stub 命令（永遠停用）

以下命令以 stub 形式存在，目前完全停用：

```javascript
// 共同模式：
export default { isEnabled: () => false, isHidden: true, name: 'stub' };
```

| 命令目錄 | 名稱 | 推測用途 |
|---------|------|---------|
| `good-claude/index.js` | good-claude | 可能是獎勵 Claude 好行為的機制 |
| `bughunter/index.js` | bughunter | 自動 bug 搜尋工具 |
| `teleport/index.js` | teleport | 傳送到遠端 session（已被其他機制取代？） |

---

## `/stickers` — 貼紙命令

來源：`src/commands/stickers/stickers.ts`

```typescript
const url = 'https://www.stickermule.com/claudecode'
openBrowser(url)
```

功能：開啟 Claude Code 的 Sticker Mule 貼紙購買頁面。

這是一個**行銷命令**，讓使用者能快速取得 Claude Code 的實體貼紙。

---

## `/think-back` — 年度回顧

來源：`src/commands/thinkback/index.ts`、`thinkback.tsx`

```typescript
{
  name: 'think-back',
  description: 'Your 2025 Claude Code Year in Review',
  isEnabled: () => checkStatsigFeatureGate_CACHED_MAY_BE_STALE('tengu_thinkback'),
}
```

**功能**：生成並播放「2025 Claude Code 年度回顧」動畫。

實現細節：
1. 從 Plugin 系統取得 `thinkback` 插件的安裝路徑
2. 讀取 `year_in_review.js`（資料）和 `player.js`（播放器）
3. 以 Node.js subprocess 執行動畫

如果插件未安裝，會提示使用者安裝。

**啟用條件**：`tengu_thinkback` feature gate 開啟

---

## `/thinkback-play` — 年度回顧（快速重播）

來源：`src/commands/thinkback-play/thinkback-play.ts`

直接重播已生成的年度回顧動畫，不需重新生成。從 InstalledPluginsV2 讀取 thinkback 插件的安裝路徑後播放。

---

## `/chrome` — Claude in Chrome 設定

來源：`src/commands/chrome/index.ts`、`chrome.tsx`

```typescript
{
  name: 'chrome',
  description: 'Claude in Chrome (Beta) settings',
  availability: ['claude-ai'],      // 需要 claude.ai OAuth
  isEnabled: () => !getIsNonInteractiveSession(),  // 需要互動模式
}
```

**功能**：管理 Claude in Chrome 瀏覽器擴充功能的整合設定。

選單選項（`MenuAction`）：
- `install-extension`：導向 `https://claude.ai/chrome` 安裝擴充功能
- `reconnect`：重新連接（`https://clau.de/chrome/reconnect`）
- `manage-permissions`：管理權限（`https://clau.de/chrome/permissions`）
- `toggle-default`：切換「預設開啟 Chrome 整合」

連接狀態：從 MCP client 狀態判斷是否已連接（`chromeClient?.type === "connected"`）。

---

## `/mobile`（別名：`/ios`、`/android`）— 手機 App QR Code

來源：`src/commands/mobile/index.ts`、`mobile.tsx`

```typescript
{
  name: 'mobile',
  aliases: ['ios', 'android'],
  description: 'Show QR code to download the Claude mobile app',
}
```

**功能**：在終端中顯示 Claude 手機 App 的 QR Code（iOS 或 Android）。

App Store URL：
- iOS：`https://apps.apple.com/app/claude-by-anthropic/id6473753684`
- Android：`https://play.google.com/store/apps/details?id=com.anthropic.claude`

使用 `qrcode` npm 套件生成 UTF-8 QR Code，在終端直接顯示。

---

## `/desktop`（別名：`/app`）— 傳送到 Claude Desktop

來源：`src/commands/desktop/index.ts`、`desktop.tsx`

```typescript
{
  name: 'desktop',
  aliases: ['app'],
  description: 'Continue the current session in Claude Desktop',
  availability: ['claude-ai'],
  isEnabled: isSupportedPlatform,  // macOS 或 Windows x64
  get isHidden() { return !isSupportedPlatform() }
}
```

**功能**：將當前對話 session 轉移到 Claude Desktop App 繼續。

支援平台：macOS 或 Windows x64（不支援 Linux 和 ARM Windows）。

實現：渲染 `DesktopHandoff` 元件（未在此分析範圍內）。

---

## `/voice` — 語音模式切換

來源：`src/commands/voice/index.ts`

```typescript
{
  name: 'voice',
  description: 'Toggle voice mode',
  availability: ['claude-ai'],
  isEnabled: () => isVoiceGrowthBookEnabled(),
  get isHidden() { return !isVoiceModeEnabled() }  // 需要 OAuth + GrowthBook
}
```

詳細分析見 [04-voice-system.md](./04-voice-system.md)。

---

## `/teleport` — 傳送到 CCR

`src/commands/teleport/index.js` 目前為純 stub，推測為早期 CCR/UltraPlan 傳送功能的命令入口，已被當前的 UltraPlan 流程或 bridge 機制取代。

---

## 命令可用性矩陣

| 命令 | 狀態 | 啟用條件 |
|------|------|---------|
| good-claude | 完全停用 | — |
| bughunter | 完全停用 | — |
| teleport | 完全停用 | — |
| stickers | 永遠可用 | 無限制 |
| think-back | Feature gate | `tengu_thinkback` |
| thinkback-play | 永遠可用 | 有安裝 thinkback 插件 |
| chrome | claude.ai + 互動模式 | availability: claude-ai |
| mobile | 永遠可用 | 無平台限制 |
| desktop | macOS 或 Win x64 | 平台檢查 |
| voice | claude.ai OAuth + GrowthBook | 雙重閘門 |
