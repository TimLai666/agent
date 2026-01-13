# Skills vs Tools：深入對比分析

## 🎯 核心差異

### Tools（工具）= "做事情"
- **執行能力**：實際執行代碼、調用 API、操作系統
- **確定性**：同樣輸入 → 同樣輸出
- **實時性**：獲取當前數據（天氣、股票、搜索）
- **副作用**：可以修改狀態（寫文件、發郵件、更新數據庫）
- **返回值**：返回實際數據給 agent

### Skills（技能）= "教做事情"
- **知識注入**：提供指導、最佳實踐、方法論
- **上下文增強**：增強 agent 的領域理解
- **指導性**：告訴 agent "如何做"而不是"幫你做"
- **靜態性**：預定義的知識，不執行代碼
- **無副作用**：純知識傳遞

## 📊 功能對比表

| 能力 | Tools | Skills | 誰更好？ |
|------|-------|--------|---------|
| **執行操作** |
| 讀取文件 | ✅ `read_file()` | ❌ | Tools 獨有 |
| 寫入文件 | ✅ `write_file()` | ❌ | Tools 獨有 |
| API 調用 | ✅ `fetch_api()` | ❌ | Tools 獨有 |
| 執行計算 | ✅ `calculate()` | ❌ | Tools 獨有 |
| **知識傳遞** |
| 代碼審查指南 | ⚠️ 簡短 docstring | ✅ 完整方法論 | Skills 更好 |
| 除錯步驟 | ⚠️ 難以傳遞 | ✅ 詳細檢查清單 | Skills 更好 |
| 最佳實踐 | ⚠️ 碎片化 | ✅ 系統化文檔 | Skills 更好 |
| **靈活性** |
| 自動激活 | ⚠️ 需主動調用 | ✅ 智能匹配 | Skills 更好 |
| 漸進載入 | ❌ 全部在系統提示 | ✅ Progressive disclosure | Skills 更好 |
| 易於更新 | ⚠️ 需修改代碼 | ✅ 編輯 Markdown | Skills 更好 |

## 💡 實際例子對比

### 例子 1：代碼審查

**使用 Tools 的方式：**
```python
@agent.tool
def review_code(code: str) -> str:
    """Review code for issues.

    Checks:
    - Syntax errors
    - Security issues
    - Performance problems
    """
    # ... 執行檢查代碼
    return "Issues found: ..."
```

**問題：**
- ❌ Docstring 太短，無法包含完整方法論
- ❌ Agent 需要自己決定調用時機
- ❌ 返回值是結果，不是指導

**使用 Skills 的方式：**
```markdown
---
name: code-review
description: Systematic code review guidance...
---

# Code Review Skill

## Review Checklist

### 1. Correctness & Logic
- Does the code do what it's supposed to do?
- Are there any logical errors?
- [詳細的 500 行審查指南...]

### 2. Security
- SQL injection vulnerabilities?
- XSS risks?
[...]
```

**優勢：**
- ✅ 完整的審查方法論
- ✅ 自動激活（當用戶說 "review code"）
- ✅ Agent 學習如何審查，而不只是調用工具

### 例子 2：文件操作

**Tools 獨有能力（Skills 做不到）：**
```python
# Tools 可以實際讀取文件
content = read_file("config.json")

# Skills 只能教你如何讀取
# ❌ 無法實際執行
```

**結論：文件操作必須用 Tools**

### 例子 3：除錯協助

**Tools 方式（有限）：**
```python
@agent.tool
def debug_code(error_msg: str) -> str:
    """Help debug errors.

    Returns: Possible solutions
    """
    # 只能返回簡短建議
    return "Try checking line 42"
```

**Skills 方式（全面）：**
```markdown
# Debugging Assistant

## Systematic Debugging Process

### 1. Understand the Problem
- What is expected behavior?
- What is actual behavior?
- [詳細步驟...]

### 2. Isolate the Issue
- Binary search through code
- Check assumptions
[...]

## Common Bug Patterns
[200+ 行除錯指南]
```

**對比：**
- Tools: 返回一個答案
- Skills: 教會 agent 整套除錯方法論

## 🎯 Skills 無法達到的 Tools 效果

### 1. 實際執行操作

```python
# ✅ Tools 可以
tool.read_file("data.csv")      # 實際讀取
tool.search_web("Python 3.12")  # 實際搜索
tool.send_email(...)            # 實際發送

# ❌ Skills 不行
# Skills 只能描述「如何讀取文件」
# 但不能實際執行讀取動作
```

### 2. 獲取實時數據

```python
# ✅ Tools 可以
weather = tool.get_weather("台北")  # 當前天氣
stock = tool.get_stock("AAPL")      # 即時股價

# ❌ Skills 不行
# Skills 的內容是靜態的
# 無法提供實時數據
```

### 3. 產生副作用

```python
# ✅ Tools 可以
tool.write_file("output.txt", data)  # 修改文件系統
tool.update_database(...)            # 修改數據庫

# ❌ Skills 不行
# Skills 是唯讀的知識
# 不會產生任何副作用
```

### 4. 返回結構化數據

```python
# ✅ Tools 可以
result = tool.parse_json(data)
# Returns: {"key": "value", "count": 42}

# ❌ Skills 不行
# Skills 只是文本指導
# 不返回數據結構
```

## 🌟 Skills 比 Tools 更好的地方

### 1. 領域知識傳遞

**Tools：**
```python
@agent.tool
def write_clean_code() -> str:
    """Write clean code following best practices."""
    return "Use meaningful names, keep functions short"
    # ⚠️ 只能給簡短建議
```

**Skills：**
```markdown
# Clean Code Skill

## Principles
1. Meaningful Names
   - Use intention-revealing names
   - Avoid disinformation
   - Make meaningful distinctions
   [詳細的 100 條規則...]

## Examples
[50+ 個實際例子]
```

**為什麼 Skills 更好：**
- ✅ 可以包含大量詳細指導（500+ 行）
- ✅ 包含具體例子和反例
- ✅ 系統化的知識結構

### 2. 自動激活 vs 手動調用

**Tools：**
```
用戶：「Review this code」
Agent 思考：要調用 review_code 工具嗎？
Agent 決定：調用 tool.review_code(code)
Tool 返回：「Found 3 issues」
```

**Skills：**
```
用戶：「Review this code」
系統：自動匹配到 code-review skill
系統：注入完整代碼審查指南到 context
Agent：根據指南進行系統化審查
```

**為什麼 Skills 更好：**
- ✅ 不需要 agent 主動決定
- ✅ 自動提供相關知識
- ✅ Agent 學習方法論而不只是調用

### 3. Token 效率

**Tools（所有工具定義都在系統提示）：**
```
System Prompt:
- read_file(path) - Read a file
- write_file(path, content) - Write a file
- search_web(query) - Search the web
- [50+ 個工具定義] ← 每次都佔用 tokens
```

**Skills（Progressive Disclosure）：**
```
啟動時：只載入元數據（~100 tokens per skill）
匹配時：只載入相關 skills
使用時：只有被激活的 skill 內容進 context
```

**節省：**
- 50 個 tools：~5,000 tokens（每次調用）
- 50 個 skills：~5,000 tokens（只有被激活時）

### 4. 可維護性

**Tools：**
```python
# 需要修改代碼
def review_code(code: str) -> str:
    """Review code.

    To update the review process:
    1. Modify this function
    2. Test the changes
    3. Deploy new version
    """
    # 需要重新部署
```

**Skills：**
```markdown
<!-- 只需編輯 Markdown -->
---
name: code-review
---

# 直接修改這個文件
## 添加新的審查項目
- New check item

<!-- 保存即生效，無需重新部署 -->
```

**為什麼 Skills 更好：**
- ✅ 非技術人員也能編輯
- ✅ 版本控制友好（Git diff 清晰）
- ✅ 無需重新部署
- ✅ 易於協作（多人編輯）

## 🤝 最佳實踐：結合使用

### 策略 1：Skills 指導 + Tools 執行

**例子：文件操作**
```
Skill: file-operations
- 教導何時用相對路徑 vs 絕對路徑
- 說明文件權限最佳實踐
- 提供錯誤處理指南

Tool: read_file(), write_file()
- 實際執行文件讀寫操作
```

**用戶輸入：**「Help me read config.json safely」

**執行流程：**
1. 激活 `file-operations` skill
2. Agent 學習安全讀取文件的最佳實踐
3. Agent 調用 `read_file("config.json")` tool
4. Agent 根據 skill 指導處理讀取結果

### 策略 2：Skills 提供上下文 + Tools 提供數據

**例子：數據分析**
```
Skill: data-analysis
- 教導數據清洗方法
- 說明統計分析步驟
- 提供可視化建議

Tool: load_csv(), calculate_stats()
- 實際載入數據
- 執行計算
```

### 策略 3：Skills 作為 Tools 的文檔

**傳統方式（Tools docstring）：**
```python
@agent.tool
def analyze_sentiment(text: str) -> dict:
    """Analyze sentiment. Returns sentiment score."""
    # ⚠️ 簡短，缺少詳細指導
```

**改進方式（Skills + Tools）：**
```python
@agent.tool
def analyze_sentiment(text: str) -> dict:
    """Analyze sentiment.

    See sentiment-analysis skill for detailed guidance.
    """

# Skills 中：
"""
# Sentiment Analysis Skill

## When to Use
[詳細說明何時使用情感分析]

## Interpretation Guide
- Score > 0.5: Positive
- Score < -0.5: Negative
[200 行詳細指南]
"""
```

## 📊 決策樹：何時用 Skills vs Tools

```
需要執行實際操作？
├─ 是 → 使用 Tools
│   └─ 例：讀文件、調 API、寫數據庫
│
└─ 否 → 需要提供知識/指導？
    ├─ 是 → 使用 Skills
    │   └─ 例：審查方法論、最佳實踐、工作流程
    │
    └─ 否 → 可能不需要額外功能
```

## 🎯 具體應用場景

### 場景 1：代碼審查
- **Skills**: code-review（提供審查方法論）
- **Tools**: read_file()（讀取代碼文件）
- **結合**: Skills 教會 agent 如何審查，Tools 提供代碼內容

### 場景 2：除錯
- **Skills**: debugging-assistant（系統化除錯流程）
- **Tools**: execute_code()（測試修復）
- **結合**: Skills 指導除錯步驟，Tools 驗證解決方案

### 場景 3：API 開發
- **Skills**: api-design（RESTful 設計原則）
- **Tools**: test_endpoint()（測試 API）
- **結合**: Skills 確保設計遵循最佳實踐，Tools 驗證功能

### 場景 4：數據分析
- **Skills**: data-analysis（分析方法論）
- **Tools**: load_data(), plot_chart()（載入和繪圖）
- **結合**: Skills 指導分析步驟，Tools 處理實際數據

## 💎 結論

### Skills 無法完全替代 Tools

**Tools 獨有能力：**
1. ❌ 執行實際操作
2. ❌ 獲取實時數據
3. ❌ 產生副作用
4. ❌ 返回結構化數據

### Skills 在某些方面優於 Tools

**Skills 優勢：**
1. ✅ 傳遞大量領域知識
2. ✅ 提供系統化方法論
3. ✅ 自動智能激活
4. ✅ Progressive disclosure
5. ✅ 易於維護和更新

### 最佳實踐

**不是二選一，而是互補！**

| 用途 | 選擇 |
|------|------|
| 需要執行操作 | Tools |
| 需要傳遞知識 | Skills |
| 需要兩者 | Skills + Tools |

**理想架構：**
```
Skills (知識層)
    ↓ 指導
Agent (決策層)
    ↓ 調用
Tools (執行層)
```

**例如：**
1. `code-review` Skill 教導審查方法
2. Agent 學習並應用這些方法
3. `read_file` Tool 提供實際代碼
4. Agent 根據 Skill 指導審查代碼
5. `write_file` Tool 保存修改建議

**Skills 和 Tools 是互補的，不是競爭關係！** 🤝
