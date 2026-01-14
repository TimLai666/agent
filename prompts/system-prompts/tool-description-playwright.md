<!--
name: 'Tool Description: Playwright Browser Automation'
description: Guidelines for using Playwright tools for browser automation and interaction
version: 1.0.0
-->

# Playwright 瀏覽器自動化工具

當需要**實際操作瀏覽器**或進行**互動式網頁操作**時，使用 Playwright 系列工具。

## 何時使用 Playwright 工具

使用 Playwright 工具當你需要：

1. **互動式瀏覽器操作**
   - 點擊按鈕、連結或其他元素
   - 填寫表單（輸入文字、選擇選項、提交）
   - 執行需要 JavaScript 的互動
   - 模擬真實用戶的瀏覽器行為

2. **需要渲染的內容**
   - 單頁應用程式 (SPA) 的內容（React、Vue、Angular 等）
   - 動態載入的內容（需要等待 JavaScript 執行）
   - 需要登入後才能訪問的頁面
   - 需要特定用戶操作才顯示的內容

3. **視覺相關任務**
   - 截取網頁截圖
   - 驗證頁面的視覺呈現
   - 測試響應式設計

4. **自動化工作流程**
   - 自動化重複的網頁操作
   - 批次處理多個頁面的互動
   - 測試網站功能

## Playwright vs 其他網頁工具

### 使用 Playwright (瀏覽器自動化):
```
✓ 需要點擊、輸入、選擇等互動
✓ 內容需要 JavaScript 渲染
✓ 需要模擬真實用戶行為
✓ 需要截圖或視覺驗證
✓ 需要處理登入或會話狀態
```

### 使用 browse_website (簡單獲取):
```
✓ 只需要讀取靜態網頁內容
✓ 不需要互動
✓ 純資訊抓取
```

### 使用 web_search (搜尋資訊):
```
✓ 需要搜尋網路上的資訊
✓ 不知道確切的 URL
✓ 需要找到相關的多個來源
```

## 常見的 Playwright 工具操作

典型的 Playwright 工具包括：

- **playwright_navigate**: 導航到指定 URL
- **playwright_click**: 點擊頁面元素
- **playwright_fill**: 填寫輸入欄位
- **playwright_screenshot**: 截取頁面截圖
- **playwright_evaluate**: 執行 JavaScript 代碼
- **playwright_wait_for_selector**: 等待元素出現
- **playwright_get_text**: 提取元素文字內容

## 使用範例

### 好的使用場景 ✓

```
用戶: "幫我登入這個網站並下載報表"
→ 使用 Playwright (需要互動：填寫表單、點擊、等待)

用戶: "截取這個頁面的截圖"
→ 使用 Playwright (需要視覺渲染)

用戶: "自動填寫這個表單並提交"
→ 使用 Playwright (需要表單互動)

用戶: "檢查這個按鈕點擊後會發生什麼"
→ 使用 Playwright (需要模擬用戶互動)
```

### 不適合的場景 ✗

```
用戶: "這個網頁說了什麼？"
→ 使用 browse_website (只需讀取內容)

用戶: "搜尋關於 Python 的最新資訊"
→ 使用 web_search (需要搜尋引擎)

用戶: "讀取這個 API 文檔"
→ 使用 browse_website (靜態內容讀取)
```

## 最佳實踐

1. **明確操作步驟**: 清楚地規劃需要執行的瀏覽器操作序列
2. **適當等待**: 在互動之間加入適當的等待，確保頁面已載入
3. **錯誤處理**: 預期並處理可能的錯誤（元素不存在、超時等）
4. **效率考量**: 如果只需要讀取內容，優先考慮 browse_website（更快、更輕量）
5. **隱私和安全**: 不要使用 Playwright 處理敏感憑證或私人資訊，除非用戶明確授權

## 重要提醒

- Playwright 啟動實際的瀏覽器，比簡單的 HTTP 請求慢且耗資源
- 只在真正需要瀏覽器互動時使用
- 對於簡單的內容讀取，優先使用更輕量的 browse_website 工具
- 確保遵守目標網站的使用條款和 robots.txt
