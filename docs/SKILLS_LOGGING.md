# Skills 日誌系統

## 📊 日誌級別與內容

### INFO 級別（重要事件）

**Skills 激活日誌：**
```
INFO - [MainAgent] Activated 2 skill(s): code-review, python-tutorial
INFO - [SubAgent] Activated 1 skill(s): debugging-assistant
```

**Skills 載入日誌：**
```
INFO - Found 5 skill files
INFO - Loaded 5 skills from /path/to/skills
INFO - SkillRegistry initialized with 5 skills (LLM scorer: disabled)
```

### DEBUG 級別（詳細資訊）

**搜尋過程：**
```
DEBUG - Searching for relevant skills (mode: keyword, max: 3, min_score: 0.10)
DEBUG - Using keyword-based skill matching
```

**匹配詳情：**
```
DEBUG -   - 'code-review': score=0.425 (matched: code, review, check)
DEBUG -   - 'python-tutorial': score=0.312 (matched: python, learn)
DEBUG - Selected top 2 skill(s)
```

**未找到 Skills：**
```
DEBUG - [MainAgent] No relevant skills found for prompt
DEBUG - No skills matched criteria
```

**個別 Skill 資訊：**
```
DEBUG -   - Skill 'code-review': Provides systematic code review guidance...
DEBUG -   - Skill 'python-tutorial': Python programming tutorial and best practices...
```

**資源載入：**
```
DEBUG - Loaded resources for skill at python-tutorial: {'scripts': [...], 'references': [...]}
DEBUG - Loaded content for skill 'python-tutorial' (~2341 chars)
```

## 🎯 實際使用示例

### 示例 1：MainAgent 使用 Skill

**用戶輸入：**
```
"Can you review this code for bugs?"
```

**日誌輸出：**
```
DEBUG - Searching for relevant skills (mode: keyword, max: 3, min_score: 0.10)
DEBUG - Using keyword-based skill matching
DEBUG -   - 'code-review': score=0.567 (matched: bugs, code, review)
DEBUG -   - 'debugging-assistant': score=0.234 (matched: bugs, code)
DEBUG - Selected top 2 skill(s)
INFO  - [MainAgent] Activated 2 skill(s): code-review, debugging-assistant
DEBUG -   - Skill 'code-review': Provides systematic code review guidance...
DEBUG -   - Skill 'debugging-assistant': Systematic debugging guidance for finding...
```

### 示例 2：SubAgent 使用 Skill

**MainAgent 調用 SubAgent：**
```python
subagent.run("Explain Python decorators to me")
```

**日誌輸出：**
```
DEBUG - Searching for relevant skills (mode: keyword, max: 3, min_score: 0.10)
DEBUG - Using keyword-based skill matching
DEBUG -   - 'python-tutorial': score=0.489 (matched: decorators, explain, python)
DEBUG - Selected top 1 skill(s)
INFO  - [SubAgent] Activated 1 skill(s): python-tutorial
DEBUG -   - Skill 'python-tutorial': Python programming tutorial and best practices...
```

### 示例 3：未找到相關 Skill

**用戶輸入：**
```
"What's the weather today?"
```

**日誌輸出：**
```
DEBUG - Searching for relevant skills (mode: keyword, max: 3, min_score: 0.10)
DEBUG - Using keyword-based skill matching
DEBUG - No skills matched criteria
DEBUG - [MainAgent] No relevant skills found for prompt
```

### 示例 4：LLM 評分模式

**啟用 LLM 評分：**
```python
skills = registry.find_relevant_skills(prompt, use_llm=True)
```

**日誌輸出：**
```
DEBUG - Searching for relevant skills (mode: LLM, max: 3, min_score: 0.10)
DEBUG - Using LLM-based skill scoring
INFO  - [MainAgent] Activated 3 skill(s): code-review, debugging-assistant, tool-usage-guide
```

## 📝 日誌格式詳解

### Skills 激活日誌格式

```
[級別] - [Agent類型] Activated [數量] skill(s): [skill名稱列表]
```

**組成部分：**
- `[MainAgent]` 或 `[SubAgent]`：哪個 agent 激活的
- 數量：激活了幾個 skills
- skill 名稱：用逗號分隔的列表

**範例：**
```
INFO - [MainAgent] Activated 3 skill(s): code-review, debugging-assistant, python-tutorial
INFO - [SubAgent] Activated 1 skill(s): tool-usage-guide
```

### Skill 匹配詳情格式

```
DEBUG -   - '[skill名稱]': score=[分數] (matched: [匹配的詞])
```

**組成部分：**
- skill 名稱：被評分的 skill
- score：相關性分數（0-1）
- matched：匹配到的關鍵詞（最多顯示 5 個）

**範例：**
```
DEBUG -   - 'code-review': score=0.567 (matched: bugs, code, quality, review, check)
DEBUG -   - 'python-tutorial': score=0.312 (matched: learn, python, tutorial)
```

## 🔧 配置日誌級別

### 查看所有日誌（包括 DEBUG）

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 只看重要日誌（INFO 及以上）

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
```

### 完全關閉 Skills 日誌

```python
import logging

# 關閉 skills_loader 的日誌
logging.getLogger('internal.skills_loader').setLevel(logging.WARNING)
```

## 📊 日誌分析

### 追蹤 Skill 使用頻率

通過 grep 分析日誌：

```bash
# 統計每個 skill 被激活的次數
grep "Activated.*skill" agent.log | \
  grep -o "skill(s): .*" | \
  sed 's/skill(s): //' | \
  tr ',' '\n' | \
  sort | uniq -c | sort -rn
```

**輸出範例：**
```
  15 code-review
   8 debugging-assistant
   5 python-tutorial
   2 tool-usage-guide
```

### 找出未匹配的查詢

```bash
# 找出沒有激活任何 skill 的查詢
grep "No relevant skills found" agent.log
```

### 分析匹配分數

```bash
# 查看所有匹配分數
grep "score=" agent.log | awk '{print $NF}'
```

## 🎯 根據日誌優化 Skills

### 場景 1：Skill 從未被激活

**問題：**
```bash
# code-optimizer skill 從未在日誌中出現
grep "code-optimizer" agent.log
# 無結果
```

**解決：**
1. 檢查 skill 的 description
2. 添加更多關鍵詞
3. 降低 min_score 閾值

### 場景 2：錯誤的 Skill 被激活

**問題：**
```
用戶：「Debug this code」
日誌：Activated: code-review, python-tutorial
預期：debugging-assistant
```

**解決：**
1. 改進 `debugging-assistant` 的 description
2. 添加 "debug", "bug", "error" 等關鍵詞
3. 減少其他 skills 中這些詞的出現

### 場景 3：太多 Skills 被激活

**問題：**
```
INFO - Activated 3 skill(s): code-review, debugging, python-tutorial, tool-usage
```

**解決：**
1. 提高 `min_score` 閾值
2. 減少 `max_skills` 數量
3. 改進 skills descriptions 使其更專一

## 📈 性能監控

### 追蹤 Skills 載入時間

```python
import time
import logging

logger = logging.getLogger('internal.skills_loader')

start = time.time()
registry = load_skill_registry()
elapsed = time.time() - start

logger.info(f"Skills loaded in {elapsed:.3f}s")
```

### 追蹤 Skill 匹配時間

已內建在 DEBUG 日誌中：

```
DEBUG - Searching for relevant skills... (開始)
DEBUG - Selected top 2 skill(s) (結束)
```

## 🔍 故障排查

### 問題：日誌中沒有 Skills 相關訊息

**可能原因：**
1. 日誌級別設置太高（只顯示 WARNING 以上）
2. Skills 功能未啟用
3. SkillRegistry 為空

**檢查：**
```python
# 檢查是否載入了 skills
registry = load_skill_registry()
print(f"Loaded {len(registry.list_names())} skills")

# 檢查日誌級別
import logging
print(logging.getLogger('internal.skills_loader').level)
```

### 問題：Skills 未被激活

**可能原因：**
1. description 中缺少相關關鍵詞
2. min_score 閾值太高
3. Prompt 太短或太模糊

**檢查：**
```python
# 手動測試匹配
skills = registry.find_relevant_skills("your prompt here")
print(f"Found {len(skills)} skills")

# 使用 DEBUG 日誌查看匹配過程
logging.getLogger('internal.skills_loader').setLevel(logging.DEBUG)
```

### 問題：LLM 評分不工作

**可能原因：**
1. 未傳入 agent 參數
2. LLM 返回格式錯誤

**檢查：**
```python
# 確保傳入了 agent
registry = load_skill_registry(enable_llm_scoring=True, agent=your_agent)

# 查看 DEBUG 日誌
# 應該看到 "Using LLM-based skill scoring"
```

## 📋 日誌清單

完整的 Skills 日誌事件：

| 事件 | 級別 | 格式 |
|------|------|------|
| Skills 載入 | INFO | `Loaded N skills from /path` |
| Registry 初始化 | INFO | `SkillRegistry initialized with N skills` |
| 搜尋開始 | DEBUG | `Searching for relevant skills` |
| 匹配模式 | DEBUG | `Using keyword-based/LLM matching` |
| Skill 評分 | DEBUG | `'skill-name': score=X.XXX` |
| 選擇結果 | DEBUG | `Selected top N skill(s)` |
| Skills 激活 | INFO | `[Agent] Activated N skill(s): ...` |
| Skill 詳情 | DEBUG | `Skill 'name': description...` |
| 無匹配 | DEBUG | `No relevant skills found` |
| 內容載入 | DEBUG | `Loaded content for skill 'name'` |
| 資源載入 | DEBUG | `Loaded resources for skill` |

## 🎯 最佳實踐

### 1. 生產環境日誌配置

```python
# 只記錄重要事件
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent.log'),
        logging.StreamHandler()
    ]
)
```

### 2. 開發環境日誌配置

```python
# 查看所有細節
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 3. 日誌分析腳本

```bash
#!/bin/bash
# analyze_skills.sh

echo "=== Skills Usage Summary ==="
echo ""
echo "Total skill activations:"
grep -c "Activated.*skill" agent.log

echo ""
echo "Skills by frequency:"
grep "Activated.*skill" agent.log | \
  grep -o "skill(s): .*" | \
  sed 's/skill(s): //' | \
  tr ',' '\n' | \
  sort | uniq -c | sort -rn

echo ""
echo "Failed matches:"
grep -c "No relevant skills found" agent.log
```

## 總結

Skills 日誌系統提供：
- ✅ **INFO 級別**：關鍵事件（skill 激活、載入）
- ✅ **DEBUG 級別**：詳細過程（搜尋、匹配、評分）
- ✅ **清晰格式**：易於解析和分析
- ✅ **Agent 識別**：區分 MainAgent 和 SubAgent
- ✅ **性能追蹤**：監控載入和匹配時間
- ✅ **故障排查**：詳細的匹配過程日誌

使用日誌可以：
1. 監控 skills 使用情況
2. 優化 skill descriptions
3. 調整匹配參數
4. 排查激活問題
5. 分析使用模式
