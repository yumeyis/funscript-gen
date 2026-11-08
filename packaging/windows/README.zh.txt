funscript-gen Windows 免安裝版
==============================

[English: README.txt]

解壓縮後即可使用，不需要安裝 Python 或其他軟體。整個資料夾可以放在任何可以寫入的位置
（例如桌面、D:\ 或隨身碟；不要放在 C:\Program Files）。刪除資料夾即等於解除安裝。

需求：Windows 10 或 11（64 位元）。圖形介面使用系統內建的 Microsoft Edge WebView2
（Windows 11 已內建；Windows 10 若沒有，程式會改用預設瀏覽器開啟）。
AI 分析需要另外架設的 vLLM 或 Ollama 伺服器，第一次使用請到「設定」分頁填寫端點與模型。


圖形介面
--------
雙擊 FunscriptGen.exe。

- 「產生」分頁：把影片拖放到框內，或按「選擇…」挑影片（直接讀取原檔，不必上傳；也可以貼上路徑），再按「產生 funscript」。
- 「批次」「預覽」分頁同樣直接讀取檔案。預覽分頁的「自動帶入同名的檔案」開著時，選了影片會自動帶入同一個資料夾
  中同名的 funscript，選了 funscript 則帶入同名的影片。
- 拖放尚未在實機桌面上確認（未驗證）；沒有反應時請改按「選擇…」。
- 腳本預設存在 data\out\<時間>\。要存到影片旁邊（和影片同名的 .funscript），
  到「設定」分頁的「輸出檔案」勾選「同時把腳本存到影片旁邊」。
  影片旁已有不是本程式產生的同名腳本時不會覆寫。
- 關閉視窗即結束程式。


指令
----
在這個資料夾開啟「命令提示字元」或 PowerShell（或把資料夾加到 PATH），執行 funscript-gen.exe：

  funscript-gen.exe generate "D:\Videos\clip.mp4"            輸出 D:\Videos\clip.funscript
  funscript-gen.exe batch "D:\Videos" -o "D:\Scripts"         整個資料夾
  funscript-gen.exe generate --help                          所有參數

指令與圖形介面共用同一份 AI 設定（data\.env）。


語言
----
介面有繁體中文與英文。用「設定」分頁最上方的「語言 / Language」清單選擇（立即生效並會記住），或在指令加 --lang en；
都沒有指定時依系統的語言。

語言包是 exe 旁 lang\ 資料夾中的 .toml 檔。要加入語言時，把 lang\_template.toml 複製成 lang\<代碼>.toml
（例如 lang\ja.toml），填寫 code 與 name 並翻譯每個 key（上方的註解列出繁體中文與英文的原文），用

  funscript-gen.exe lang check lang\ja.toml

檢查後重新整理頁面，清單中就會出現。


data 資料夾
-----------
程式寫入的檔案全部在 data\ 中，不會寫到使用者目錄：
  .env                 AI 設定（含 API 金鑰）
  .webui-*.json        圖形介面記住的設定（含語言）
  out\                 圖形介面產生的腳本
  cache\               AI 回應、部位偵測模型與結果等快取（可以刪除，會重新產生）
  tmp\                 暫存檔（可以刪除）
  app.log              圖形介面的記錄（無法啟動時查看）

更新版本：解壓縮新版後，把舊版的 data 資料夾複製過去即可保留設定與快取。


常見問題
--------
- 第一次執行時 Windows 顯示「Windows 已保護您的電腦」：程式沒有數位簽章。
  按「其他資訊」→「仍要執行」。
- 有獨立顯示卡時，光流與部位偵測會自動使用 GPU（可在「設定」分頁的「運算裝置」調整）。


使用注意、免責聲明與授權
------------------------
- 請只處理你有合法使用權的影片，並僅供符合當地法定成年年齡之人士使用；嚴禁處理任何違法或涉及未成年人之內容。
- 產生的 .funscript 若搭配實體致動器／電動裝置使用，請自行先在預覽中檢查並設定安全的行程範圍與速度上限；
  本軟體依「現況（AS IS）」提供，開發者不對任何硬體損壞、資料遺失或人身傷害負任何責任。
- 本專案採用 PolyForm Noncommercial License 1.0.0 授權（禁止商業使用，見 LICENSE.txt），第三方套件與模型授權說明見 THIRD_PARTY_NOTICES.md。
  本專案使用 Anthropic Claude（Claude Code）協作開發。
