# 01 — Buddy AI 寵物系統完整分析

## 概覽

Buddy 是 Claude Code 內建的 AI 寵物（Companion）系統，以 ASCII art 精靈的形式陪伴在使用者輸入框旁。整個系統由 `src/buddy/` 目錄管理，共 6 個檔案。

Feature flag：`feature('BUDDY')`（bun:bundle 編譯期 flag）

上線時間窗口：
- Teaser 期：2026 年 4 月 1 日－7 日（本地時間，非 UTC，刻意拉開 Twitter 流量）
- 正式上線：2026 年 4 月 1 日起永久可用
- 內部人員（USER_TYPE === 'ant'）：永遠顯示

---

## 物種系統（18 種）

來源：`src/buddy/types.ts`

所有物種名稱在源碼中以 `String.fromCharCode()` 編碼，目的是規避 `excluded-strings.txt` 的 build 掃描（其中 `duck` 可能與某個 model codename canary 衝突）。

| 物種 | 說明 |
|------|------|
| duck | 鴨子（可能受 canary 掃描保護） |
| goose | 鵝 |
| blob | 無定形黏液怪 |
| cat | 貓 |
| dragon | 龍 |
| octopus | 章魚 |
| owl | 貓頭鷹 |
| penguin | 企鵝 |
| turtle | 烏龜 |
| snail | 蝸牛 |
| ghost | 幽靈 |
| axolotl | 墨西哥蠑螈 |
| capybara | 水豚 |
| cactus | 仙人掌 |
| robot | 機器人 |
| rabbit | 兔子 |
| mushroom | 蘑菇 |
| chonk | 胖貓（chonk 是網路迷因：胖乎乎的動物） |

---

## 稀有度系統

來源：`src/buddy/types.ts`、`src/buddy/companion.ts`

### 稀有度等級與權重

| 稀有度 | 權重 | 機率 | 顏色主題 | 星星 |
|--------|------|------|----------|------|
| common | 60 | 60% | inactive（灰） | ★ |
| uncommon | 25 | 25% | success（綠） | ★★ |
| rare | 10 | 10% | permission（藍） | ★★★ |
| epic | 4 | 4% | autoAccept（紫） | ★★★★ |
| legendary | 1 | 1% | warning（金） | ★★★★★ |

### 稀有度影響

1. **帽子**：common 稀有度無帽子，其他等級會從帽子池隨機選擇
2. **屬性地板**（`RARITY_FLOOR`）：
   - common: 5；uncommon: 15；rare: 25；epic: 35；legendary: 50
3. **亮晶晶（shiny）**：1% 機率，所有稀有度均可觸發

---

## 屬性（Stats）系統

5 個屬性，每個 1–100 分：

| 屬性名 | 說明 |
|--------|------|
| DEBUGGING | 除錯能力 |
| PATIENCE | 耐心 |
| CHAOS | 混亂值 |
| WISDOM | 智慧 |
| SNARK | 嗆辣度 |

**滾點機制**（`rollStats`）：
- 一個「峰值屬性」：floor + 50 + rand(30)，上限 100
- 一個「廢屬性」：max(1, floor - 10 + rand(15))
- 其餘屬性：floor + rand(40)

---

## 帽子系統（8 種）

來源：`src/buddy/sprites.ts`

| 帽子 | ASCII 渲染 |
|------|-----------|
| none | （無） |
| crown | `\^^^/` |
| tophat | `[___]` |
| propeller | `-+-` |
| halo | `(   )` |
| wizard | `/^\` |
| beanie | `(___)` |
| tinyduck | `,>` |

---

## 眼睛系統（6 種）

`· ✦ × ◉ @ °`

---

## Sprite 系統

來源：`src/buddy/sprites.ts`

每個物種有 **3 幀動畫**（idle 擺動），格式為 5 行、12 字符寬的 ASCII art。`{E}` 是眼睛的佔位符，運行時替換為實際眼睛字符。

動畫序列（`CompanionSprite.tsx`）：
```
IDLE_SEQUENCE = [0, 0, 0, 0, 1, 0, 0, 0, -1, 0, 0, 2, 0, 0, 0]
```
- 大部分時間停在 frame 0（靜止）
- 偶爾 frame 1（輕微晃動）
- 稀少出現 frame 2（特效：煙霧、天線等）
- `-1` 表示眨眼（frame 0 + 閉眼效果）

Tick：500ms

---

## 確定性生成機制

來源：`src/buddy/companion.ts`

### 演算法

```
salt = 'friend-2026-401'
seed = hashString(userId + salt)
rng = mulberry32(seed)
→ 決定 rarity、species、eye、hat、shiny、stats
```

使用 **Mulberry32**（輕量種子隨機數生成器），保證：
- 同一 userId 永遠得到同一個寵物
- 不能藉由編輯 config 文件偽造稀有度

### 儲存策略

- `StoredCompanion`（持久化）：只儲存 `name`、`personality`、`hatchedAt`
- Bones（物種/稀有度等外觀）：每次從 userId hash **重新生成**，永不持久化
- 好處：物種改名或 SPECIES 陣列調整不會破壞舊有寵物

---

## 靈魂（Soul）生成

來源：`src/buddy/prompt.ts`

第一次孵化時，Claude 會為寵物生成 `name` 和 `personality`（儲存在 config.companion）。

寵物透過 `companionIntroText()` 將自身介紹附加到 system prompt：
> "A small {species} named {name} sits beside the user's input box and occasionally comments in a speech bubble."

當使用者直接叫寵物名字時，主模型被要求簡短回應（1 行以內），speech bubble 獨立處理。

---

## UI 互動

來源：`src/buddy/CompanionSprite.tsx`

### Speech Bubble
- 顯示 20 ticks（~10 秒）
- 最後 6 ticks（~3 秒）淡出提示即將消失
- 最大寬度 30 字符，自動換行

### Pet 互動（/buddy pet 指令）
- 顯示心形漂浮動畫（5 幀，~2.5 秒）：
  ```
  ♥    ♥
  ♥  ♥   ♥
  ♥   ♥  ♥
  ♥  ♥      ♥
  ·    ·   ·
  ```

---

## 觸發與通知

來源：`src/buddy/useBuddyNotification.tsx`

- **Teaser 通知**：啟動時若無已孵化寵物且在 Teaser 時間窗內，顯示彩虹色 `/buddy` 提示 15 秒
- **PromptInput 高亮**：`findBuddyTriggerPositions()` 在使用者輸入 `/buddy` 時高亮顯示

---

## 設計彩蛋

1. `duck` 物種名稱用 `String.fromCharCode(0x64,0x75,0x63,0x6b)` 編碼 → 規避內部 canary 字符串掃描
2. Salt 值 `'friend-2026-401'` 包含日期暗示（2026-04-01，即 4 月 1 日愚人節發布）
3. `chonk` 物種 → 網路迷因中胖動物的稱呼
4. `tinyduck` 帽子 → 對 duck 物種的致敬
5. 稀有度顏色用 Theme key（`autoAccept`, `warning` 等）而非硬編碼顏色，與整體設計系統整合
