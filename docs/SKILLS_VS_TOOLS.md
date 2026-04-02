# Skills vs Tools（現行）

## 分工

1. Tools
- 執行實際操作：讀寫檔案、查詢、命令執行、外部呼叫。

2. Skills
- 提供方法論與流程：透過 `use_skill` 取得操作指南和資源路徑。

## 本專案實際模式

目前採用 tool-based skills：

1. agent 判斷是否需要某技能
2. 呼叫 `use_skill("skill-name")`
3. 取得 skill 內容與 bundled resources 路徑
4. 再搭配其他 tools 完成任務

## 何時先用 skill

1. 任務有明確領域流程（例如 code review、debug、docx/pdf 流程）
2. 需要 skill 中的 scripts/references/assets

## 何時直接用 tool

1. 已知步驟單純且不需領域框架
2. 只是一次性讀寫/查詢操作

## 一句話

Skills 決定「怎麼做」，Tools 負責「把它做完」。
