# 配置遷移指南

> 從環境變數遷移到 SQLite 配置系統

## ⚠️ 重要

新版本不再支援環境變數配置。請按照以下步驟完成遷移。

## 遷移優勢

- ✅ **更靈活** - 為不同 agent 配置不同模型
- ✅ **更易管理** - CLI 圖形介面，無需手動編輯 `.env`
- ✅ **更多選擇** - 支援 GitHub Copilot 等新提供者
- ✅ **更穩定** - 配置持久化儲存在資料庫中

## 快速遷移

### 1. 檢查現有配置

查看你的 `.env` 檔案：

```bash
# Linux/Mac
cat .env

# Windows
type .env
```

常見變數：
```bash
OPENAI_API_KEY=sk-...
MODEL_NAME=gpt-4
MODEL_TEMPERATURE=0.2
```

### 2. 開啟配置介面

```bash
uv run main.py --config
```

### 3. 新增提供者

**OpenAI 官方**：
```
選項: 2 (新增 OpenAI 相容 API 提供者)
ID: openai
名稱: OpenAI
Base URL: (留空)
API Key: sk-...
```

**Anthropic Claude**：
```
選項: 2
ID: anthropic
名稱: Anthropic
Base URL: https://api.anthropic.com
API Key: sk-ant-...
```

**GitHub Copilot**：
```
選項: 3 (新增 GitHub Copilot 提供者)
ID: github-copilot
名稱: GitHub Copilot
方式: 1 (瀏覽器登入) ⭐ 推薦
```

### 4. 配置 Agent

```
選項: 6 (設定 Agent)
Agent: main
提供者: 選擇剛才建立的提供者
模型: gpt-4 (或其他模型名稱)
Temperature: 0.2
```

### 5. 驗證配置

```bash
# 查看所有配置
uv run main.py --config
選項: 1 (列出所有提供者)
選項: 7 (列出所有 Agent 設定)
```

### 6. 清理舊配置（可選）

遷移完成後，可以刪除 `.env` 檔案或註釋掉相關環境變數。

## 多 Agent 配置範例

```bash
# 1. 新增多個提供者
# - openai: OpenAI GPT-4
# - anthropic: Claude
# - github-copilot: GitHub Copilot

# 2. 為不同 agent 配置不同模型
main          -> openai        -> gpt-4
marketing     -> anthropic     -> claude-3-5-sonnet-20241022
testing       -> github-copilot -> gpt-4o
```

## 故障排除

### 找不到配置

**錯誤**：`ValueError: No model configuration found for agent: main`

**解決**：執行 `uv run main.py --config` 並完成步驟 3-4

### Token 無效

**錯誤**：API 返回 401/403

**解決**：
1. 檢查 API Key 是否正確
2. 重新設定提供者：`uv run main.py --config` → 選項 4 (刪除提供者) → 重新新增

### Windows gh 命令找不到

**問題**：使用 gh CLI 自動獲取 token 失敗

**解決**：使用瀏覽器登入方式（推薦），參見 [GitHub 瀏覽器登入指南](GITHUB_BROWSER_LOGIN.md)

## 相關文檔

- [完整配置指南](CONFIG_GUIDE.md)
- [Windows 快速開始](WINDOWS_QUICK_START.md)
- [GitHub 瀏覽器登入](GITHUB_BROWSER_LOGIN.md)
