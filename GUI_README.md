# GUI 模式使用說明

## 概述

此項目現在提供兩種運行模式：
1. **CLI 模式** (`main.py`) - 命令行界面
2. **GUI 模式** (`main.py --gui`) - 圖形用戶界面

## 安裝依賴

確保已安裝所有依賴（包括 PySide6 和 opencc-python-reimplemented）：

```bash
uv sync
```

## 運行方式

### CLI 模式（默認）

```bash
uv run python main.py
```

### GUI 模式

```bash
uv run python main.py --gui
```

## GUI 功能說明

### 界面組成

1. **動畫球體** - 中央的綠色動畫球體，表示 AI 助手正在運行
2. **對話框** - 顯示 AI 的回應
3. **輸入區域** - 雙擊視窗可顯示/隱藏
   - 文字輸入框
   - 語音按鈕（🎤）
   - 發送按鈕

### 交互方式

1. **文字對話**：
   - 在輸入框中輸入文字
   - 按 Enter 或點擊「發送」按鈕

2. **語音輸入**：
   - 點擊「🎤」按鈕
   - 開始說話
   - 系統會自動識別並發送

3. **視窗操作**：
   - 拖拽：點擊視窗任意位置並拖動
   - 雙擊：顯示/隱藏輸入框

## 與 CLI 版本的差異

| 特性 | CLI 模式 | GUI 模式 |
|------|----------|----------|
| 輸入方式 | 命令行 + 語音 | 圖形界面 + 語音 |
| 輸出方式 | 終端輸出 | 對話框 |
| 視覺效果 | 純文字 | 動畫球體 |
| 啟動命令 | `uv run python main.py` | `uv run python main.py --gui` |

## 技術實現

### 組件

- **GUI 框架**：PySide6 (Qt for Python)
- **異步處理**：QThread + asyncio
- **語音識別**：Whisper + SpeechRecognition
- **繁簡轉換**：opencc-python-reimplemented
- **AI 架構**：pydantic-ai + MainAgent

### 架構

```
main.py (--gui 模式)
├── GUIAgentApp (主應用類)
│   ├── MainWindow (GUI 窗口)
│   │   ├── ArcWidget (動畫球體)
│   │   ├── Speech Bubble (對話框)
│   │   └── Input Container (輸入區)
│   ├── MainAgent (AI 代理)
│   ├── VoiceManager (語音管理)
│   └── AIWorker (異步 AI 處理線程)
```

## 故障排除

### GUI 無法啟動

確保已安裝 PySide6：
```bash
uv sync
```

### 語音識別失敗

確保：
1. 麥克風已連接
2. 系統權限允許訪問麥克風
3. 已安裝 pyaudio：
   ```bash
   # Windows: pip install pipwin
   # pipwin install pyaudio
   ```

### OpenCC 繁簡轉換失敗

如果遇到 OpenCC 問題，項目使用 `opencc-python-reimplemented` 作為純 Python 後備方案。

## 未來改進

- [ ] 添加多主題支持
- [ ] 改善響應式佈局
- [ ] 添加設置面板
- [ ] 支持多語言界面
- [ ] 添加聊天歷史查看功能
