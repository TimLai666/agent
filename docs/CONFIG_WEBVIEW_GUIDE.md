# GUI WebView 配置功能

## 功能說明

現在在 GUI 模式下，配置頁面會在內建的 WebView 窗口中打開，無需切換到外部瀏覽器。

## 使用方法

### 1. 通過右上角按鈕打開

在 GUI 主窗口的右上角，點擊 ⚙️ 按鈕即可打開配置頁面。

### 2. 通過命令打開

在 GUI 輸入框中輸入以下命令：

```
/config-web
```

### 3. 通過程序啟動時直接打開

```bash
uv run main.py --gui
```

然後在 GUI 中使用上述方法打開配置頁面。

## WebView 窗口功能

配置 WebView 窗口包含以下功能：

- **重新整理** (🔄) - 重新加載配置頁面
- **返回** (←) - 返回上一頁
- **前進** (→) - 前進到下一頁
- **關閉** (✕) - 關閉配置窗口

## 技術細節

- 使用 `PySide6-WebEngine` 提供 WebView 支持
- 配置頁面運行在本地 Flask 服務器上 (http://127.0.0.1:5000)
- GUI 模式下自動使用 WebView，CLI 模式下仍使用外部瀏覽器
- WebView 窗口大小為 1200x800，可在代碼中調整

## 測試

運行測試腳本：

```bash
uv run test_config_webview.py
```

這將單獨測試 WebView 功能，無需啟動完整的 AI 助手。

## 優勢

✅ **無需切換應用** - 配置頁面在 GUI 內打開  
✅ **更好的集成** - 與 AI 助手無縫整合  
✅ **更快的訪問** - 無需等待外部瀏覽器啟動  
✅ **更好的 UX** - 統一的用戶體驗

## 故障排除

### WebView 無法顯示

確保已安裝 PySide6-WebEngine：

```bash
pip install PySide6-WebEngine
```

### 配置服務器未啟動

確保 Flask 服務器正在運行。GUI 會自動啟動，但如果遇到問題，可以手動檢查：

```python
from internal.services import config_webui
url = config_webui.ensure_webui_running()
print(f"Config UI at: {url}")
```

### 窗口無法打開

檢查日誌輸出以獲取詳細錯誤信息。
