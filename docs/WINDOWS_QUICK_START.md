# Windows 快速開始指南

## 推薦方式：瀏覽器登入 🌐

**最簡單的方式，不需要安裝任何額外工具！**

### 1. 執行配置程式

```powershell
uv run main.py --config
```

### 2. 新增 GitHub Copilot 提供者

```
選項: 3
提供者 ID: github-copilot
顯示名稱: GitHub Copilot
Token 方式: 1 (瀏覽器登入) ⭐
```

### 3. 完成認證

- 程式會自動打開瀏覽器
- 在 GitHub 頁面輸入顯示的代碼
- 授權後自動完成

✅ **完成！無需其他步驟。**

詳細說明請參考：[GitHub 瀏覽器登入指南](GITHUB_BROWSER_LOGIN.md)

---

## 替代方式：使用 gh CLI

如果你需要使用 gh CLI（例如用於其他用途），請按照以下步驟：

### 1. 安裝 GitHub CLI

```powershell
winget install GitHub.cli
```

### 2. ⚠️ 重啟 PowerShell

**重要**：安裝後必須完全關閉並重新開啟 PowerShell！

Windows 安裝程式會修改 PATH 環境變數，但當前 PowerShell 不會自動重新載入。

### 3. 驗證安裝

```powershell
gh --version
```

應該顯示：`gh version 2.x.x (...)`

如果看到「找不到 'gh' 命令」：
- 檢查是否已重啟 PowerShell
- 檢查 PATH：`$env:Path -split ';' | Select-String 'GitHub CLI'`

### 4. 登入 GitHub

**方式 A：Token 登入（推薦）**

1. 產生 token：https://github.com/settings/tokens
   - Scopes: `repo`, `read:org`, `copilot`
2. 執行：
   ```powershell
   "你的token" | gh auth login --with-token
   ```

**方式 B：瀏覽器登入**

```powershell
gh auth login
# 選擇 GitHub.com → HTTPS → 瀏覽器登入
```

### 5. 使用 gh CLI 自動取得

```powershell
uv run main.py --config
# 選項 3 → 選項 2 (自動取得)
```

## 故障排除

### gh 命令找不到

**原因**：PowerShell 沒有重新載入 PATH

**解決**：
1. 完全關閉所有 PowerShell 視窗
2. 重新開啟 PowerShell
3. 執行 `gh --version` 驗證

### 手動添加 PATH（如果重啟無效）

```powershell
# 檢查 gh.exe 位置
Get-Command gh -ErrorAction SilentlyContinue

# 如果找不到，手動添加（僅當前會話）
$env:Path += ";C:\Program Files\GitHub CLI"

# 驗證
gh --version
```

### 永久添加 PATH

1. 按 `Win + X`，選擇「系統」
2. 點擊「進階系統設定」
3. 點擊「環境變數」
4. 在「系統變數」中找到 `Path`
5. 點擊「編輯」
6. 新增：`C:\Program Files\GitHub CLI`
7. 確定並重啟 PowerShell

## 相關文檔

- **[GitHub 瀏覽器登入](GITHUB_BROWSER_LOGIN.md)** - 瀏覽器認證完整指南（推薦）
- [配置指南](CONFIG_GUIDE.md) - 完整配置說明
- [遷移指南](MIGRATION_GUIDE.md) - 從環境變數遷移
