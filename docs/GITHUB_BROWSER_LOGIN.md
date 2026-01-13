# GitHub 瀏覽器登入指南

## 🎯 最簡單的方式：使用內建 OAuth 認證

不需要安裝 `gh` CLI，不需要手動產生 token，只需要一個瀏覽器！

## 快速開始

### 1. 執行配置程式

```powershell
uv run main.py --config
```

### 2. 選擇新增 GitHub Copilot 提供者

在選單中輸入：
```
3
```

### 3. 輸入基本資訊

```
輸入提供者 ID（例如：github-copilot）: github-copilot
輸入顯示名稱: GitHub Copilot
```

### 4. 選擇瀏覽器登入

```
取得 GitHub Token 方式:
  1. 瀏覽器登入 (推薦，無需安裝 gh CLI)
  2. 自動取得 (使用 gh CLI)
  3. 手動輸入

選擇 (1/2/3, 預設 1): 1
```

### 5. 完成認證

程式會自動：
1. 啟動本地回調伺服器（port 8765）
2. 打開你的預設瀏覽器
3. 顯示類似以下訊息：

```
🔐 正在啟動 GitHub 裝置認證流程...

📱 請在瀏覽器中訪問：https://github.com/login/device
   並輸入代碼：ABCD-1234
   (代碼將在 900 秒後過期)

⏳ 等待授權完成...
```

4. 在瀏覽器中：
   - 訪問 https://github.com/login/device
   - 輸入顯示的代碼（例如：`ABCD-1234`）
   - 點擊「Continue」
   - 授權應用程式存取權限
   - 看到「Device activated!」訊息

5. 回到終端，會顯示：
```
✓ 認證成功！
✓ 成功取得 Token: ghp_xxxxxxxxxxxx...
✓ 成功新增提供者: github-copilot
```

## 技術細節

### 使用的認證方式

這個系統使用 **GitHub Device Flow**，這是 GitHub 官方推薦用於桌面應用程式的 OAuth 方式。

**優點**：
- ✅ 不需要 client_secret（更安全）
- ✅ 不需要處理複雜的回調 URL
- ✅ 適合無法嵌入瀏覽器的應用
- ✅ 用戶體驗友好

**流程**：
```
1. 應用程式請求裝置碼 → GitHub 返回 user_code 和 device_code
2. 應用程式顯示 user_code 給用戶
3. 用戶在瀏覽器中輸入 user_code
4. 應用程式輪詢 GitHub 檢查授權狀態
5. 用戶完成授權後，應用程式獲得 access_token
```

### 需要的權限（Scopes）

自動請求以下權限：
- `repo` - 存取倉庫（用於 Copilot）
- `read:org` - 讀取組織資訊
- `copilot` - 使用 GitHub Copilot

### OAuth App 設定

程式使用預設的 Client ID：`Iv1.b507a08c87ecfe98`

如果你想使用自己的 OAuth App：
1. 訪問 https://github.com/settings/developers
2. 點擊「New OAuth App」
3. 填寫資訊：
   - Application name: `Your App Name`
   - Homepage URL: `http://localhost`
   - Authorization callback URL: `http://localhost:8765/callback`
4. 獲取 Client ID
5. 修改 `internal/services/github_oauth.py` 中的 `CLIENT_ID`

## 常見問題

### Q: 瀏覽器沒有自動打開？

**A**: 手動複製程式顯示的 URL 到瀏覽器中打開。

### Q: 看到「Port 8765 already in use」錯誤？

**A**: 有其他程式正在使用 8765 端口。你可以：
1. 關閉佔用該端口的程式
2. 等待幾分鐘後重試
3. 或使用「手動輸入 token」方式

### Q: 認證超時怎麼辦？

**A**: Device Flow 的代碼有效期是 15 分鐘。如果超時：
1. 重新執行配置命令
2. 更快地完成瀏覽器授權步驟

### Q: 我想撤銷授權怎麼辦?

**A**: 訪問 https://github.com/settings/applications
- 找到你的應用程式
- 點擊「Revoke」撤銷授權

### Q: Token 會過期嗎？

**A**: GitHub OAuth tokens 預設不會過期，除非你手動撤銷。如果 token 過期或失效，重新執行瀏覽器登入即可。

### Q: 這個方式安全嗎？

**A**: 是的！Device Flow 是 GitHub 官方推薦的桌面應用認證方式：
- 不需要在應用中儲存 client_secret
- Token 直接從 GitHub 獲取
- 使用標準的 OAuth 2.0 流程
- 符合安全最佳實踐

## 與其他方式的比較

| 方式 | 優點 | 缺點 |
|------|------|------|
| **瀏覽器登入（Device Flow）** | ✅ 最簡單<br>✅ 不需要 gh CLI<br>✅ 安全 | ⚠️ 需要網路連線 |
| gh CLI 自動取得 | ✅ 一鍵完成<br>✅ 可重複使用 | ❌ 需要先安裝並設定 gh CLI |
| 手動輸入 Token | ✅ 完全控制<br>✅ 可用於 CI/CD | ❌ 需要手動產生<br>❌ 步驟較多 |

## 下一步

成功設定提供者後：

1. **設定 Agent 使用該提供者**：
```powershell
uv run main.py --config
# 選擇 6 - 設定 Agent 模型
```

2. **測試連線**：
```powershell
uv run main.py
# 開始與 Agent 對話
```

3. **查看所有設定**：
```powershell
uv run main.py --config
# 選擇 1 - 列出所有提供者
# 選擇 7 - 列出所有 Agent 設定
```

## 相關文件

- [完整配置指南](CONFIG_GUIDE.md)
- [Windows 快速開始](WINDOWS_QUICK_START.md)
- [GitHub Device Flow 官方文件](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow)
