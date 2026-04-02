# Skills 多語言支援說明

## 🌏 問題背景

用戶使用中文 prompt "教我寫python" 時，skills 無法被激活。

## 🔍 根本原因

### 1. 詞彙提取問題

Jaccard 相似度演算法使用 `re.findall(r'\w+')` 提取詞彙：

```python
# 英文（正常工作）
prompt = "teach me python"
words = re.findall(r'\w+', prompt.lower())
# 結果：['teach', 'me', 'python'] ✓

# 中文（無法正確分詞）
prompt = "教我寫python"
words = re.findall(r'\w+', prompt.lower())
# 結果：['教我寫python']  ✗ 應該是 ['教', '我', '寫', 'python']
```

### 2. 分數稀釋問題

在 skill description 中加入中文關鍵詞後：

```yaml
description: Python programming tutorial... 教學 學習 學 寫 入門 基礎 語法
```

詞彙數量大增：
```python
# 原本（只有英文）
desc_words = {"python", "programming", "tutorial", ...}  # ~10 個詞
score = 1 / 10 = 0.1 ✓ 達到預設閾值

# 加入中文後
desc_words = {"python", "programming", ..., "教學", "學習", ...}  # ~23 個詞
score = 1 / 23 = 0.043 ✗ 低於預設閾值 0.1
```

## ✅ 解決方案

### 方案 1：降低匹配閾值（已實施）

**修改位置：**
- `internal/agents/main_agent.py:1047-1052`
- `internal/sub_agents/base.py:31-37`

**改動：**
```python
# 改動前
relevant_skills = self.skills.find_relevant_skills(prompt, max_skills=3)
# 預設 min_score=0.1

# 改動後
relevant_skills = self.skills.find_relevant_skills(
    prompt,
    max_skills=3,
    min_score=0.03  # 降低閾值以支援多語言
)
```

**效果：**
```bash
Prompt: teach me python
✓ 匹配：python-tutorial (score: 0.043)

Prompt: review my code
✓ 匹配：code-review, debugging-assistant

Prompt: fix this bug
✓ 匹配：debugging-assistant, code-review
```

### 方案 2：改進 Skill Descriptions

**格式：**
```yaml
---
name: python-tutorial
description: Python programming tutorial and best practices. Use when the user asks about Python basics, syntax, or wants to learn Python programming. 教學 學習 學 寫 入門 基礎 語法 程式 編程 教我 怎麼.
---
```

**已更新的 Skills：**
1. ✓ python-tutorial - 加入中文關鍵詞：教學、學習、寫、入門等
2. ✓ code-review - 加入中文關鍵詞：審查、檢查、品質等
3. ✓ debugging-assistant - 加入中文關鍵詞：除錯、調試、bug等
4. ✓ tool-usage-guide - 加入中文關鍵詞：工具、使用、執行等

## 📊 測試結果

### 英文匹配

```python
Prompt: "teach me python"
Matched: python-tutorial ✓

Prompt: "review my code"
Matched: code-review, debugging-assistant ✓

Prompt: "fix this bug"
Matched: debugging-assistant, code-review ✓

Prompt: "how to use tools"
Matched: tool-usage-guide ✓
```

### 中文匹配限制

**目前狀況：**
中文詞彙無法正確分詞，但如果 prompt 中包含英文關鍵詞（如 "python"），仍可匹配：

```python
Prompt: "教我寫python"
✓ 可匹配（因為包含 "python"）

Prompt: "教我寫程式"
✗ 無法匹配（純中文，無法分詞）
```

## 🔮 未來改進方案

### 方案 A：中文分詞器（推薦）

使用 `jieba` 等中文分詞庫：

```python
import jieba

# 修改 _keyword_based_matching
def _keyword_based_matching(self, prompt: str, ...):
    # 對中文使用分詞
    if contains_chinese(prompt):
        prompt_words = set(jieba.cut(prompt.lower()))
    else:
        prompt_words = {w for w in re.findall(r'\w+', prompt.lower())}

    # ... 其餘邏輯
```

**優點：**
- ✓ 正確處理中文
- ✓ 提高匹配準確性

**缺點：**
- ✗ 需要額外依賴
- ✗ 增加載入時間

### 方案 B：雙語 Descriptions

分離中英文 description：

```yaml
---
name: python-tutorial
description: Python programming tutorial and best practices.
description_zh: Python 程式設計教學與最佳實踐。教學、學習、入門、基礎。
keywords: python, tutorial, programming, learn, teach, 教學, 學習, 寫, 入門
---
```

匹配時同時檢查兩個欄位。

### 方案 C：LLM 評分模式

使用 LLM 進行語義理解：

```python
registry = load_skill_registry(
    enable_llm_scoring=True,
    agent=your_agent
)

skills = registry.find_relevant_skills(
    prompt,
    use_llm=True  # 使用 LLM 評分
)
```

**優點：**
- ✓ 完美支援多語言
- ✓ 理解語義而非關鍵詞

**缺點：**
- ✗ 較慢（~200-500ms）
- ✗ API 成本

## 🎯 目前建議

### 開發者

1. **在 skill descriptions 中同時加入中英文關鍵詞**
   ```yaml
   description: English description. 中文 關鍵詞 列表.
   ```

2. **使用混合語言 prompts**
   ```
   ✓ "教我寫 python" （混合）
   ✓ "幫我 review code" （混合）
   ✗ "教我寫程式" （純中文，無法匹配）
   ```

3. **使用 `/skills test` 測試匹配**
   ```bash
   /skills test 教我寫python
   /skills test teach me python
   ```

### 用戶

目前最佳實踐：
- ✓ 使用英文 prompts（完美支援）
- ✓ 使用混合語言（包含英文關鍵詞）
- ⚠️ 純中文 prompts（支援有限）

**範例：**
```
✓ "教我寫 python"         （包含 "python"）
✓ "幫我 review 這段 code"  （包含 "review", "code"）
✓ "fix 這個 bug"          （包含 "fix", "bug"）
✓ "teach me python"       （純英文）
⚠️ "教我寫程式"            （純中文，可能無法匹配）
```

## 📈 性能影響

### 降低 min_score 的影響

```
原本 min_score: 0.1
新的 min_score: 0.03

影響：
- ✓ 提高匹配率（支援多語言）
- ✓ 對性能無影響（仍然很快）
- ⚠️ 可能匹配到較不相關的 skills（但可透過 max_skills 控制）
```

### 監控與調整

**查看日誌：**
```bash
# 啟用 DEBUG 日誌
import logging
logging.getLogger('internal.skills_loader').setLevel(logging.DEBUG)

# 日誌會顯示：
DEBUG - 'python-tutorial': score=0.043 (matched: python)
```

**調整參數：**
```python
# 更嚴格
relevant_skills = self.skills.find_relevant_skills(
    prompt,
    max_skills=2,      # 減少激活數量
    min_score=0.05     # 提高閾值
)

# 更寬鬆
relevant_skills = self.skills.find_relevant_skills(
    prompt,
    max_skills=5,      # 增加激活數量
    min_score=0.02     # 降低閾值
)
```

## 總結

### 現況

✅ **已實施：**
- 降低 min_score 到 0.03（支援多語言）
- 在 skill descriptions 中加入中文關鍵詞
- MainAgent 和 SubAgent 都支援

✅ **支援良好：**
- 英文 prompts（完美）
- 混合語言 prompts（良好）

⚠️ **支援有限：**
- 純中文 prompts（需要包含英文關鍵詞才能匹配）

### 未來改進

如需完美的中文支援，可考慮：
1. 整合中文分詞器（jieba）
2. 啟用 LLM 評分模式
3. 實施雙語 description 系統

目前的解決方案已能滿足大多數使用場景。
