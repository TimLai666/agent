# 02 — Computer Use 整合架構分析

## 概覽

Computer Use（代號 **Chicago**，feature flag 名稱 `tengu_malort_pedway`）是 Claude Code 在 macOS 上直接控制電腦的功能——截圖、滑鼠點擊、鍵盤輸入、App 管理。

架構位置：`src/utils/computerUse/`（15 個檔案）

---

## 平台限制

**僅支援 macOS**（`process.platform === 'darwin'`）。
`createCliExecutor` 在非 Darwin 平台拋出錯誤：
> `"Computer control is macOS-only."`

Windows 的 Computer Use 由另一系統處理（非此模組）。

---

## 啟用條件（多層閘門）

來源：`src/utils/computerUse/gates.ts`

```typescript
function getChicagoEnabled(): boolean {
  // Ant 人員且有 monorepo 存取權 → 停用（除非 ALLOW_ANT_COMPUTER_USE_MCP=1）
  if (process.env.USER_TYPE === 'ant' && process.env.MONOREPO_ROOT_DIR &&
      !isEnvTruthy(process.env.ALLOW_ANT_COMPUTER_USE_MCP)) {
    return false
  }
  return hasRequiredSubscription() && readConfig().enabled
}
```

### 訂閱需求
- 必須是 **Max** 或 **Pro** 訂閱
- Ant 員工可繞過訂閱限制（`USER_TYPE === 'ant'`）

### GrowthBook 旗標
- Feature name：`tengu_malort_pedway`（malort = 芝加哥特產苦艾酒，pedway = 芝加哥地下通道）
- 預設值：`{ enabled: false, ... }`

---

## Sub-gates 配置

| 設定 | 預設值 | 說明 |
|------|--------|------|
| `enabled` | false | 主開關 |
| `pixelValidation` | false | 像素層級驗證 |
| `clipboardPasteMultiline` | true | 多行文字用剪貼簿貼上 |
| `mouseAnimation` | true | 拖曳時平滑滑鼠動畫 |
| `hideBeforeAction` | true | 動作前隱藏其他視窗 |
| `autoTargetDisplay` | true | 自動選擇目標顯示器 |
| `clipboardGuard` | true | 剪貼簿保護（貼上後還原） |
| `coordinateMode` | `'pixels'` | 座標模式（pixels 或 normalized） |

---

## 原生模組架構

### 兩個 Native 模組

1. **`@ant/computer-use-input`**（Rust/enigo）
   - 滑鼠操作：移動、點擊、按壓、拖曳、滾輪
   - 鍵盤操作：按鍵、輸入文字
   - 查詢：滑鼠位置、前景 App 資訊

2. **`@ant/computer-use-swift`**（Swift/NSWorkspace + SCContentFilter）
   - 截圖（`SCContentFilter`，支援排除特定 App）
   - App 管理：列出已安裝/運行中、獲取前景 App、隱藏/顯示視窗
   - 顯示器管理：列出顯示器、取得尺寸

### 載入策略
- Swift 模組：工廠函式 `createCliExecutor()` 初始化時就載入
- Input 模組（Rust）：第一次執行滑鼠/鍵盤操作時才懶載入（純截圖流程不需要它）

---

## CLI vs Cowork（Desktop App）的差異

來源：`src/utils/computerUse/executor.ts` 頂部註解

| 面向 | Claude Code CLI | Cowork（Desktop App） |
|------|----------------|----------------------|
| Click-through | 無（無視窗） | `BrowserWindow.setIgnoreMouseEvents(true)` |
| Host Bundle ID | sentinel（`com.anthropic.claude-code.cli-no-window`） | 實際 bundle ID |
| 剪貼簿 | `pbcopy`/`pbpaste` | Electron `clipboard` 模組 |
| 終端識別 | `__CFBundleIdentifier` / fallback 表 | 無需 |

---

## 核心功能實現

### 截圖
- JPEG 品質：0.75
- 先計算目標尺寸（`targetImageSize` + `API_RESIZE_PARAMS`），讓 API transcoder 不做伺服器端縮放
- 自動排除終端模擬器視窗

### 滑鼠動畫（拖曳）
- Ease-out-cubic，60fps
- 速度：2000 px/sec，最長 0.5 秒
- 僅用於 drag 操作（非 click），讓目標 App 有時間處理 `.leftMouseDragged` 事件

### 鍵盤輸入
- 單鍵或修飾鍵組合（`ctrl+shift+a` 格式）
- **Escape 特殊處理**：bare Escape 會通知 CGEventTap 不觸發使用者中止回調

### 剪貼簿安全貼上
- 先儲存使用者剪貼簿
- 寫入要貼的內容
- **讀回驗證**：寫入失敗時不觸發 Cmd+V（避免貼錯）
- 貼上後等 100ms（避免競爭條件）
- `finally` 塊還原使用者剪貼簿

---

## 終端感知（Terminal Awareness）

來源：`src/utils/computerUse/common.ts`

支援的終端模擬器對應表：
```
iTerm.app  → com.googlecode.iterm2
Apple_Terminal → com.apple.Terminal
ghostty    → com.mitchellh.ghostty
kitty      → net.kovidgoyal.kitty
WarpTerminal → dev.warp.Warp-Stable
vscode     → com.microsoft.VSCode
```

目的：截圖時排除終端本身，避免截到 Claude Code 介面。

---

## MCP 整合方式

來源：`src/utils/computerUse/setup.ts`

Computer Use 以 **in-process MCP server** 的形式掛載（`scope: 'dynamic'`），工具名稱格式：`mcp__computer-use__*`。

這個命名是刻意的：API 後端偵測到 `mcp__computer-use__*` 工具名稱後，會自動在 system prompt 注入 Computer Use 可用性提示（`COMPUTER_USE_MCP_AVAILABILITY_HINT`）。Cowork Desktop App 使用相同命名是同樣原因。

---

## ESC 熱鍵安全機制

來源：`src/utils/computerUse/escHotkey.ts`

安裝 CGEventTap 監聽 Escape 按鍵。若 Claude 本身合成 Escape（如模擬關閉 dialog），需要呼叫 `notifyExpectedEscape()` 先行豁免，否則 CGEventTap 會誤判為使用者要中止 Computer Use。

---

## App 名稱白名單

來源：`src/utils/computerUse/appNames.ts`

包含常見 macOS App 的 bundle ID 對應顯示名稱，用於權限請求 UI 顯示友善名稱（而非 bundle ID）。

---

## 安全分析

1. **訂閱閘門**：限制 Max/Pro 使用者才能啟用
2. **GrowthBook 閘門**：遠端可緊急關閉
3. **Terminal 排除**：截圖不含 Claude Code 自身介面
4. **剪貼簿保護**：操作後自動還原使用者剪貼簿
5. **Ant 人員限制**：有 monorepo 存取的 Ant 員工預設停用（防止內部誤用）
