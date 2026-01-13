# Web UI 配置指南

> 最簡單的配置方式 - 圖形化介面

## 🚀 快速開始

### 1. 啟動 Web UI

```bash
uv run main.py --config-web
```

瀏覽器會自動打開 `http://127.0.0.1:5000`

### 2. 新增提供者

#### OpenAI 相容 API

1. 點擊「➕ 新增提供者」
2. 選擇「OpenAI 相容 API」
3. 填寫資訊：
   - **提供者 ID**: `openai` (或 `anthropic`, `azure`)
   - **顯示名稱**: `OpenAI` (或你喜歡的名稱)
   - **Base URL**: 留空（使用 OpenAI 預設）或自訂
   - **API Key**: 你的 API Key
4. 點擊「新增」

#### GitHub Copilot

1. 點擊「➕ 新增提供者」
2. 選擇「GitHub Copilot」
3. 填寫資訊：
   - **提供者 ID**: `github-copilot`
   - **顯示名稱**: `GitHub Copilot`
4. 點擊「🔐 瀏覽器登入」
   - 程式會自動打開 GitHub 認證頁面
   - 在頁面中輸入顯示的代碼
   - 完成後 Token 會自動填入
5. 點擊「新增」

### 3. 設定 Agent

1. 切換到「🤖 Agent 配置」標籤
2. 點擊「➕ 設定 Agent」
3. 填寫資訊：
   - **Agent 名稱**: `main` (或其他 agent)
   - **提供者**: 選擇剛才建立的提供者
   - **模型名稱**: 自動列出可用模型，直接選擇 ✨
   - **Temperature**: 0.2（預設）
4. 點擊「儲存」

## ✨ 主要功能

### 📋 提供者管理

- ✅ 新增/刪除提供者
- ✅ 查看提供者狀態
- ✅ 一鍵 GitHub OAuth 認證

### 🤖 Agent 配置

- ✅ 為不同 agent 配置不同模型
- ✅ **自動列出提供者可用模型**（無需手動輸入）
- ✅ 即時預覽配置

### 🔄 自動模型列表

當你選擇提供者後，系統會：

1. **OpenAI 相容 API**: 自動從 API 獲取模型列表
2. **GitHub Copilot**: 列出所有支援的模型
3. **失敗時**: 提供常見模型的後備列表

無需記憶模型名稱，直接選擇即可！

## 💡 使用技巧

### 快速設定 OpenAI

```
提供者 ID: openai
顯示名稱: OpenAI
Base URL: (留空)
API Key: sk-...
```

### 快速設定 Anthropic Claude

```
提供者 ID: anthropic
顯示名稱: Anthropic
Base URL: https://api.anthropic.com
API Key: sk-ant-...
```

### 快速設定本地 Ollama

```
提供者 ID: ollama
顯示名稱: Ollama Local
Base URL: http://localhost:11434
API Key: (留空)
```

## 🔍 常見問題

### Q: 模型列表載入失敗？

**A**: 系統會自動使用後備列表。常見原因：
- API Key 無效
- Base URL 錯誤
- 網路連線問題

### Q: 如何更新提供者資訊？

**A**: 目前需要刪除後重新新增。未來版本會支援編輯功能。

### Q: 可以同時開啟 CLI 和 Web UI 嗎？

**A**: 可以！兩者共用同一個資料庫，配置會同步。

### Q: Web UI 在哪個端口運行？

**A**: 預設 `127.0.0.1:5000`，僅本機可存取。

### Q: 如何停止 Web UI？

**A**: 在終端按 `Ctrl+C`

## 📖 相關文檔

- [完整配置指南](CONFIG_GUIDE.md) - 包含 CLI 使用方式
- [GitHub 瀏覽器登入](GITHUB_BROWSER_LOGIN.md) - OAuth 認證詳解
- [遷移指南](MIGRATION_GUIDE.md) - 從環境變數遷移

## 🎨 介面預覽

### 提供者管理
- 卡片式設計，清晰顯示每個提供者
- 一鍵刪除，確認後才執行
- 顯示認證狀態（已設定/未設定）

### Agent 配置
- 下拉選單選擇提供者
- **自動載入模型列表**
- 即時調整 temperature

### OAuth 認證
- 點擊按鈕自動打開瀏覽器
- Token 自動填入表單
- 無需手動複製貼上

## 🔧 進階使用

### 自訂端口

```bash
# 編輯 internal/services/config_webui.py
# 修改 start_webui() 的 port 參數
```

### 允許外部存取

```bash
# 修改 host 參數從 "127.0.0.1" 到 "0.0.0.0"
# ⚠️ 注意：這會讓其他電腦也能存取
```

### Debug 模式

```python
# 在 main.py 中
start_webui(host="127.0.0.1", port=5000, debug=True)
```

## 🆚 Web UI vs CLI

| 功能 | Web UI | CLI |
|------|--------|-----|
| 使用難度 | ⭐⭐⭐⭐⭐ 極簡單 | ⭐⭐⭐ 中等 |
| 視覺化 | ✅ 圖形化介面 | ❌ 純文字 |
| 模型列表 | ✅ 自動顯示 | ❌ 需手動輸入 |
| GitHub 認證 | ✅ 一鍵完成 | ⚠️ 需手動處理 |
| 配置預覽 | ✅ 即時顯示 | ❌ 無預覽 |
| 適用場景 | 日常使用、快速配置 | 腳本自動化、遠端伺服器 |

**推薦**：優先使用 Web UI，簡單直觀！
