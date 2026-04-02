# Sub-Agents

**範圍：** `internal/sub_agents/` — 領域專屬的子代理

## 概述

此目錄包含專業化的子代理（sub-agents），每個代理專注於特定領域的任務。這些子代理由主代理在需要專業協助時調用。

## 📁 目錄結構

子代理按照功能領域組織：

```
internal/sub_agents/
├── bonus/              # 特殊用途代理
├── design/             # 設計相關代理
├── engineering/        # 工程開發代理
├── marketing/          # 行銷推廣代理
├── product/            # 產品管理代理
├── project-management/ # 專案管理代理
├── studio-operations/  # 工作室營運代理
└── testing/            # 測試與品質保證代理
```

## 📋 子代理列表

### 工程開發 (engineering/)

- **ai-engineer** - AI/ML 功能整合
- **backend-architect** - 後端架構設計
- **devops-automator** - DevOps 自動化
- **frontend-developer** - 前端開發
- **mobile-app-builder** - 行動應用開發
- **rapid-prototyper** - 快速原型製作
- **test-writer-fixer** - 測試撰寫與修復

### 產品管理 (product/)

- **feedback-synthesizer** - 使用者反饋分析
- **sprint-prioritizer** - 衝刺優先級管理
- **trend-researcher** - 趨勢研究

### 行銷推廣 (marketing/)

- **app-store-optimizer** - App Store 優化
- **content-creator** - 內容創作
- **growth-hacker** - 成長駭客
- **instagram-curator** - Instagram 策展
- **reddit-community-builder** - Reddit 社群建立
- **tiktok-strategist** - TikTok 策略
- **twitter-engager** - Twitter 互動

### 設計 (design/)

- **brand-guardian** - 品牌守護者
- **ui-designer** - UI 設計
- **ux-researcher** - UX 研究
- **visual-storyteller** - 視覺故事
- **whimsy-injector** - 趣味注入

### 專案管理 (project-management/)

- **experiment-tracker** - 實驗追蹤
- **project-shipper** - 專案發布
- **studio-producer** - 工作室製作人

### 工作室營運 (studio-operations/)

- **analytics-reporter** - 分析報告
- **finance-tracker** - 財務追蹤
- **infrastructure-maintainer** - 基礎設施維護
- **legal-compliance-checker** - 法規合規檢查
- **support-responder** - 支援回應

### 測試與品質保證 (testing/)

- **api-tester** - API 測試
- **performance-benchmarker** - 效能基準測試
- **test-results-analyzer** - 測試結果分析
- **tool-evaluator** - 工具評估
- **workflow-optimizer** - 工作流程優化

### 特殊用途 (bonus/)

- **joker** - 幽默助手
- **studio-coach** - 工作室教練

## 🎯 主動觸發的代理

某些代理會在特定情況下自動觸發：

- **studio-coach** - 複雜多代理任務開始時或代理需要指導時
- **test-writer-fixer** - 實現功能、修復錯誤或修改代碼後
- **whimsy-injector** - UI/UX 變更後
- **experiment-tracker** - 添加功能標誌時

## 🔧 新增子代理

要新增新的子代理：

1. 在相應的領域目錄中創建新的 `.md` 檔案
2. 遵循現有格式（包含 YAML frontmatter）
3. 包含 3-4 個詳細的使用範例
4. 撰寫完整的系統提示（500+ 字）
5. 使用實際任務進行測試

## 📚 相關文檔

- [專案知識庫](../../AGENTS.md) - 整體專案架構
- [Internal 模組指南](../AGENTS.md) - Internal 模組說明
- [Sub-Agents 指南](AGENTS.md) - 子代理詳細指南

## 🔗 另見

- `registry.py` - 子代理註冊邏輯
- 各領域目錄中的 `.md` 檔案 - 個別代理定義
