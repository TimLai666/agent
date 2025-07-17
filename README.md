
# agent

這是一個日常 AI agent，類似 Siri，目標是協助用戶完成日常任務。

## 特色
- 透過定義各種函式，讓 AI 能執行多種操作
- 可擴充支援語音輸入等互動方式
- 易於擴展，未來可整合更多功能

## 未來規劃
- 封裝所有feature以成為物件導向設計(OOP)
- 支援語音輸入/輸出
    - 介面優化
    - 自動辨識停止語音輸入
- 增加更多日常生活相關的自動化功能

## 使用方式

本專案建議使用 [uv](https://github.com/astral-sh/uv) 來安裝依賴與運行。

### 安裝依賴

```sh
uv sync
```

#### 安裝 Playwright

```sh
uv run playwright install
```

### 啟動專案

```sh
uv run main.py
```
