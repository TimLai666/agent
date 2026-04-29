新增對話紀錄功能(保存session)到DEFAULT_TIM_AGENT_ROOT(~/.tim-agent)下子資料夾下
- 對話紀錄存原始對話(含每句話的時間戳)，不受壓縮與剪裁影響，並且紀錄對話的session_id與timestamp
- 再chat模式的ui可以選擇舊的對話紀錄來繼續對話，或是刪除舊的對話紀錄(刪除前需確認)
- 新增對話搜尋工具，可以搜尋對話紀錄，就算該對話已經超出context(例如經過壓縮或剪裁)也能找到相關資訊，並且可以傳參數選擇搜尋目前session(current)或是特定session(session_id)或是全部session(all)的對話紀錄
- sdk模式可以傳入參數覆蓋預設的對話紀錄路徑，讓使用者可以自訂對話紀錄的儲存位置