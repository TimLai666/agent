# Skills 指令使用指南

## 📝 可用指令

### 1. `/skills` 或 `/skills list`
列出所有已載入的 skills

**用法：**
```
/skills
/skills list
```

**輸出範例：**
```
Available skills (5 total):
- code-review: Provides systematic code review guidance. Use when the user asks to...
- debugging-assistant: Systematic debugging guidance for finding and fixing code is...
- example-skill: An example skill demonstrating the skills system. Use this when...
- python-tutorial: Python programming tutorial and best practices. Use when the...
- tool-usage-guide: Guidance on when and how to use tools effectively. Use when the...
```

**特點：**
- 顯示 skill 數量
- 列出所有 skill 名稱和描述
- 長描述會自動截斷（> 80 字元）

---

### 2. `/skills info <name>`
顯示特定 skill 的詳細資訊

**用法：**
```
/skills info code-review
/skills info python-tutorial
```

**輸出範例：**
```
Skill: python-tutorial
Description: Python programming tutorial and best practices. Use when the user asks about Python basics, syntax, or wants to learn Python programming.

Bundled resources:
  Scripts: hello_world.py
  References: cheatsheet.md
  Assets: template.py

Content preview:
----------------------------------------
# Python Tutorial Skill

This skill provides Python programming guidance and includes bundled resources for learning.

## When to Use

- User wants to learn Python basics
- User asks about Python syntax or features
- User needs Python code examples
...
----------------------------------------
```

**特點：**
- 完整的 skill 名稱和描述
- 列出 bundled resources（scripts/references/assets）
- 顯示內容預覽（前 500 字元）
- 如果內容更長會顯示剩餘字元數

**錯誤處理：**
```
/skills info unknown-skill
→ Skill 'unknown-skill' not found. Use /skills to see available skills.
```

---

### 3. `/skills test <prompt>`
測試哪些 skills 會匹配給定的提示

**用法：**
```
/skills test Can you review my code?
/skills test I have a bug in my program
/skills test Explain Python decorators
```

**輸出範例：**
```
Testing prompt: 'Can you review my code?'
Matched 2 skill(s):

1. code-review
   Provides systematic code review guidance.

2. debugging-assistant
   Systematic debugging guidance for finding and fixing code is...
```

**特點：**
- 顯示匹配的 skill 數量
- 按相關性排序（最相關的在前）
- 最多顯示 5 個匹配結果
- 顯示每個 skill 的簡短描述

**無匹配範例：**
```
/skills test What's the weather?
→ No skills matched for prompt: 'What's the weather?'
```

---

### 4. `/skills reload`
重新載入所有 skills（從磁碟）

**用法：**
```
/skills reload
```

**輸出範例：**
```
Skills reloaded successfully. Loaded 5 skills.
```

**使用場景：**
- 修改了 skill 文件（SKILL.md）
- 新增了新的 skill
- 刪除了某個 skill
- 不想重啟 agent 就應用更改

**錯誤處理：**
```
Failed to reload skills: [error message]
```

---

## 🎯 實際使用示例

### 場景 1：查看有哪些 skills

```
> /skills

Available skills (5 total):
- code-review: Provides systematic code review guidance...
- debugging-assistant: Systematic debugging guidance...
- example-skill: An example skill demonstrating...
- python-tutorial: Python programming tutorial...
- tool-usage-guide: Guidance on when and how to use tools...
```

### 場景 2：了解 code-review skill

```
> /skills info code-review

Skill: code-review
Description: Provides systematic code review guidance. Use when the user asks to review code, check code quality, find bugs, or improve code structure.

Content preview:
----------------------------------------
# Code Review Skill

This skill provides comprehensive code review guidance following industry best practices.

## When to Use

Activate this skill when the user:
- Asks to review their code
- Wants to check code quality
...
----------------------------------------
```

### 場景 3：測試 skill 匹配

```
> /skills test Help me fix this bug

Testing prompt: 'Help me fix this bug'
Matched 2 skill(s):

1. debugging-assistant
   Systematic debugging guidance for finding and fixing code is...

2. code-review
   Provides systematic code review guidance.
```

### 場景 4：修改 skill 後重新載入

```
# 1. 編輯 skills/my-skill/SKILL.md
# 2. 重新載入

> /skills reload

Skills reloaded successfully. Loaded 5 skills.

# 3. 驗證更改
> /skills info my-skill
[顯示更新後的內容]
```

---

## 📊 指令對比

| 指令 | 用途 | 參數 | 輸出 |
|------|------|------|------|
| `/skills` | 列出所有 skills | 無 | 簡短列表 |
| `/skills list` | 列出所有 skills | 無 | 簡短列表 |
| `/skills info <name>` | 查看詳細資訊 | skill 名稱 | 詳細資訊 |
| `/skills test <text>` | 測試匹配 | 提示文本 | 匹配結果 |
| `/skills reload` | 重新載入 | 無 | 成功/失敗 |

---

## 🔍 與其他指令的對比

### `/tools` vs `/skills`

```
> /tools
Available tools:
- read_file: Read a file from disk
- write_file: Write content to a file
...

> /skills
Available skills (5 total):
- code-review: Provides systematic code review guidance...
- debugging-assistant: Systematic debugging guidance...
...
```

**差異：**
- **Tools**: 可執行的功能（讀文件、調 API）
- **Skills**: 知識和指導（如何審查代碼、如何除錯）

### `/subagents` vs `/skills`

```
> /subagents
Available sub-agents:
- researcher: Research and find information
- analyst: Analyze data and provide insights
...

> /skills
Available skills (5 total):
- code-review: Provides systematic code review guidance...
...
```

**差異：**
- **SubAgents**: 專門的 agent（有自己的 prompt 和行為）
- **Skills**: 知識模組（注入到任何 agent 的 context）

---

## 💡 進階使用技巧

### 1. 組合使用指令

```bash
# 查看有哪些 skills
> /skills

# 找出最相關的 skill
> /skills test I need to debug this error

# 查看該 skill 的詳細內容
> /skills info debugging-assistant

# 然後直接問問題（skill 會自動激活）
> Help me debug this error: [error details]
```

### 2. 開發 Skills 工作流

```bash
# 1. 創建新 skill
$ mkdir skills/my-new-skill
$ nano skills/my-new-skill/SKILL.md

# 2. 測試是否載入
> /skills
[檢查列表中有沒有 my-new-skill]

# 3. 測試匹配
> /skills test my test prompt
[看看是否正確匹配]

# 4. 查看詳細內容
> /skills info my-new-skill

# 5. 修改後重新載入
$ nano skills/my-new-skill/SKILL.md
> /skills reload

# 6. 實際使用
> [觸發 skill 的提示]
```

### 3. 調試 Skills 不激活的問題

```bash
# 問題：skill 沒有被激活

# Step 1: 確認 skill 已載入
> /skills
[檢查 skill 是否在列表中]

# Step 2: 測試匹配
> /skills test your prompt here
[看看是否匹配到預期的 skill]

# Step 3: 檢查 skill 描述
> /skills info your-skill-name
[確認 description 包含相關關鍵詞]

# Step 4: 改進 description
$ nano skills/your-skill/SKILL.md
[添加更多關鍵詞到 description]

# Step 5: 重新載入並測試
> /skills reload
> /skills test your prompt here
```

---

## 🎓 教學範例

### 範例 1：新用戶探索

```
新用戶：這個系統有什麼功能？

> /help
[查看所有指令]

> /skills
[查看有哪些 skills]

> /skills info example-skill
[了解 skills 是什麼]

> /tools
[查看有哪些 tools]

> /subagents
[查看有哪些 sub-agents]
```

### 範例 2：找出相關 Skill

```
用戶：我想學習 Python

> /skills test I want to learn Python

Testing prompt: 'I want to learn Python'
Matched 1 skill(s):

1. python-tutorial
   Python programming tutorial and best practices...

> /skills info python-tutorial
[查看詳細內容]

> Teach me Python basics
[直接開始學習，skill 會自動激活]
```

### 範例 3：開發者調整 Skills

```
開發者：我想添加一個新的 skill

# 1. 創建 skill
$ mkdir skills/api-design
$ cat > skills/api-design/SKILL.md << 'EOF'
---
name: api-design
description: RESTful API design best practices. Use when designing APIs, REST endpoints, or web services.
---

# API Design Skill
...
EOF

# 2. 載入並驗證
> /skills reload
Skills reloaded successfully. Loaded 6 skills.

> /skills info api-design
[驗證內容正確]

> /skills test How to design a REST API?
Testing prompt: 'How to design a REST API?'
Matched 1 skill(s):

1. api-design
   RESTful API design best practices...

# 3. 測試使用
> Help me design a REST API for user management
[skill 應該會自動激活]
```

---

## 📋 快速參考

```bash
# 列表
/skills              # 列出所有 skills
/skills list         # 同上

# 詳情
/skills info <name>  # 查看 skill 詳細資訊

# 測試
/skills test <text>  # 測試 prompt 匹配

# 重載
/skills reload       # 重新載入所有 skills

# 幫助
/help               # 查看所有指令
```

---

## ⚙️ 配置和自定義

### 修改匹配參數

如果需要調整匹配行為，可以修改 `system.py` 中的參數：

```python
# 在 _test_skill_matching() 中
skills = main_agent.skills.find_relevant_skills(
    prompt,
    max_skills=5,      # 最多返回幾個
    min_score=0.1,     # 最低分數閾值
    use_llm=False      # 是否使用 LLM 評分
)
```

### 自定義輸出格式

可以修改 `_format_skills_list()` 等函數來自定義輸出格式。

---

## 🐛 故障排查

### 問題 1: `/skills` 顯示 "No skills loaded."

**原因：**
- skills 目錄不存在
- skills 目錄是空的
- 所有 SKILL.md 文件格式錯誤

**解決：**
```bash
# 檢查 skills 目錄
$ ls skills/

# 檢查是否有 SKILL.md 文件
$ find skills -name "SKILL.md"

# 查看日誌
[啟動時應該看到 "Loaded N skills" 日誌]
```

### 問題 2: `/skills info <name>` 找不到 skill

**原因：**
- skill 名稱拼寫錯誤
- skill 未載入

**解決：**
```bash
# 先列出所有 skills
> /skills

# 使用正確的名稱
> /skills info correct-name

# 如果還是找不到，重新載入
> /skills reload
```

### 問題 3: `/skills test` 沒有匹配到預期的 skill

**原因：**
- skill 的 description 中缺少關鍵詞
- min_score 閾值太高

**解決：**
```bash
# 查看 skill 的 description
> /skills info your-skill

# 修改 SKILL.md 添加關鍵詞
$ nano skills/your-skill/SKILL.md

# 重新載入並測試
> /skills reload
> /skills test your prompt
```

---

## 總結

Skills 指令提供了強大的管理功能：

✅ **查看**: `/skills` - 快速查看所有可用 skills
✅ **詳情**: `/skills info <name>` - 深入了解特定 skill
✅ **測試**: `/skills test <text>` - 驗證匹配邏輯
✅ **重載**: `/skills reload` - 無需重啟即可更新

這些指令讓 skills 系統更容易使用、調試和維護！
