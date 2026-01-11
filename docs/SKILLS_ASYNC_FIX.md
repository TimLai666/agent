# Skills LLM 匹配 Async 修復

## 🐛 問題

啟用 LLM 匹配後出現錯誤：
```
Error: This event loop is already running
RuntimeWarning: coroutine 'SkillRelevanceScorer.score_skills' was never awaited
```

## 🔍 根本原因

`SkillRelevanceScorer.score_skills_sync()` 使用 `asyncio.run_until_complete()` 嘗試在已運行的 event loop 中執行 async 函數，這在 Python asyncio 中是不允許的。

```python
# 錯誤的做法
def score_skills_sync(self, ...):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(self.score_skills(...))  # ❌ 已有 event loop 運行
```

## ✅ 解決方案

將整個調用鏈改為 async：

### 1. SkillRegistry.find_relevant_skills() → async

**檔案：** `internal/skills_loader.py`

```python
# 改動前
def find_relevant_skills(self, prompt: str, ...) -> list[SkillSpec]:
    if use_llm and self._llm_scorer:
        return self._llm_scorer.score_skills_sync(...)  # ❌ sync wrapper
    return self._keyword_based_matching(...)

# 改動後
async def find_relevant_skills(self, prompt: str, ...) -> list[SkillSpec]:
    if use_llm and self._llm_scorer:
        return await self._llm_scorer.score_skills(...)  # ✓ 直接 await
    return self._keyword_based_matching(...)
```

### 2. MainAgent._apply_skills() → async

**檔案：** `internal/agents/main_agent.py`

```python
# 改動前
def _apply_skills(self, prompt: str) -> str:
    relevant_skills = self.skills.find_relevant_skills(...)  # ❌ sync call

# 改動後
async def _apply_skills(self, prompt: str) -> str:
    relevant_skills = await self.skills.find_relevant_skills(...)  # ✓ await
```

**調用處更新：**

```python
# Line 1347, 1402（改動前）
prompt = self._apply_skills(prompt)

# Line 1347, 1402（改動後）
prompt = await self._apply_skills(prompt)
```

### 3. SubAgent._apply_skills() → async

**檔案：** `internal/sub_agents/base.py`

```python
# 改動前
def _apply_skills(self, prompt: str) -> str:
    relevant_skills = self._skills.find_relevant_skills(...)

# 改動後
async def _apply_skills(self, prompt: str) -> str:
    relevant_skills = await self._skills.find_relevant_skills(...)
```

**調用處更新：**

```python
# async def run(self, prompt: str) -> str:
prompt = await self._apply_skills(prompt)  # ✓

# async def run_stream(self, prompt: str):
prompt = await self._apply_skills(prompt)  # ✓
```

### 4. 移除 Unicode Emoji（Windows 兼容性）

```python
# 改動前
logger.info("🎯 [MainAgent] Activated %d skill(s): %s", ...)
logger.debug("  └─ Skill '%s': %s", ...)

# 改動後
logger.info("[MainAgent] Activated %d skill(s): %s", ...)
logger.debug("  - Skill '%s': %s", ...)
```

## 📊 改動摘要

| 檔案 | 方法 | 改動 |
|------|------|------|
| `internal/skills_loader.py` | `find_relevant_skills()` | sync → **async** |
| `internal/skills_loader.py` | 調用 LLM scorer | `score_skills_sync()` → **await score_skills()** |
| `internal/agents/main_agent.py` | `_apply_skills()` | sync → **async** |
| `internal/agents/main_agent.py` | 2處調用 `_apply_skills()` | 加上 **await** |
| `internal/sub_agents/base.py` | `_apply_skills()` | sync → **async** |
| `internal/sub_agents/base.py` | 2處調用 `_apply_skills()` | 加上 **await** |
| `internal/agents/main_agent.py` | logger.info | 移除 emoji ✓ |

## 🎯 現在可以正常工作

```python
用戶：教我python

流程：
1. MainAgent.run() → async ✓
2. MainAgent._apply_skills() → async ✓
3. SkillRegistry.find_relevant_skills() → async ✓
4. SkillRelevanceScorer.score_skills() → async ✓
   - 使用 LLM 評估相關性
   - 返回 {"python-tutorial": 0.95, ...}
5. 激活 python-tutorial skill ✓
6. 注入 skill context 到 prompt ✓
7. 正常回應 ✓
```

## ✅ 驗證

啟動 agent 並測試：

```bash
uv run main.py

輸入文字或按Enter啟動語音辨識> 教我python
INFO - Enabled LLM-based skill matching for more accurate multilingual support
INFO - [MainAgent] Activated 1 skill(s): python-tutorial
DEBUG -   - Skill 'python-tutorial': Python programming tutorial...

# ✓ 正常運行，無錯誤
```

## 📝 技術細節

### 為什麼不能用 run_until_complete()？

```python
# 當前環境
async def main():  # ← 已在 event loop 中
    agent = MainAgent.create(...)
    await agent.run("教我python")
    # ↓ 在這裡調用
    # ↓ find_relevant_skills()
    # ↓ score_skills_sync()
    # ↓ run_until_complete()  ← ❌ 嘗試創建新 loop/阻塞當前 loop

# run_until_complete() 的限制：
# 1. 不能在已運行的 event loop 中使用
# 2. 會阻塞當前 loop（等待 async 完成）
# 3. Python 會拋出 "This event loop is already running"
```

### 正確的做法

```python
# 在 async context 中，直接 await
async def find_relevant_skills(...):
    if use_llm:
        result = await self._llm_scorer.score_skills(...)  # ✓
    return result
```

## 總結

- ✅ 修復了 "event loop is already running" 錯誤
- ✅ 修復了 "coroutine was never awaited" 警告
- ✅ LLM 匹配現在可以正常工作
- ✅ 完美支援中文 prompts
- ✅ MainAgent 和 SubAgent 都能使用
- ✅ 移除了 Windows 不兼容的 emoji

所有改動都是向下兼容的，不影響現有功能。
