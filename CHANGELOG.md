# CHANGELOG

每次修改的摘要，新的在最上面；仍有效的決策與最近的開發紀錄在 [PLAN.md](PLAN.md)，2026-11-08 以前的完整數字在 [docs/archive/PLAN-archive.md](docs/archive/PLAN-archive.md)。`## vX.Y.Z — 日期` 標記一個發布的版本，包含它以下到上一個版本標題之間的條目（版本規則見 [DEVELOPMENT.md](DEVELOPMENT.md#版本與發布)）。v1.0.0 以前的條目記的 commit 標題屬於未公開的開發歷史，公開的儲存庫從 v1.0.0 開始。

## 2026-11-12 — 預覽播放器的「上下顛倒」（commit: `Add an Upside down tool to the preview player for a stretch of a scene`）
- 目的：專案審視 A3：長鏡頭只有一段方向相反時，只能整個鏡頭反轉。
- 修改：`preview.py` 新增 `mirrorScene` 與「上下顛倒」按鈕、`M` 鍵（作用在選取的點，沒選時是目前鏡頭）；語言包、README（中英）、PLAN。
- 驗證：`uv run pytest` 通過（新增 node 測試）；無頭 Chromium 驗證按鈕與選取後的鏡像、版面。沒有在真實影片上實測拖曳框選。屬 MINOR（新功能）。

## 2026-11-12 — 重新產生時保留手動反轉（commit: `Keep the scenes flipped by hand when generating again`）
- 目的：專案審視 A2：手動反轉是使用者最花時間的修正，重新產生就消失。
- 修改：`pipeline.carry_flips`；`webui.run` 沿用分析時保留反轉、重新分析時依輸出方向對應；語言包 `web.run.flips_kept`；README（中英）、PLAN。
- 驗證：`uv run pytest` 通過（新增 2 項單元與整合測試）；沒有改自動輸出，沒有跑驗證分數；重新分析時的對應沒有用真實影片驗證。屬 MINOR（行為改變：以前一定丟掉）。

## 2026-11-12 — 移出驗證的 3D 動畫系列（commit: `Remove the 3D animation series from the validation set`）
- 目的：使用者要求移除該系列，以後不用它驗證。
- 修改：`validation.toml` 移除 7 段（現在 dev 13、test 11、holdout 7、dev2 22、holdout2 25，共 78 段）、`ignore_low_flow` 清空；DEVELOPMENT 的分組與驗證表、README 的段數、`report.py` 的方向把握統計改用 78 段的數字；PLAN 記錄與影響。`valid/` 中的檔案已刪除（不在 git 中）。
- 驗證：數字由同一份執行結果排除該系列重算，沒有重跑；預設 F1 dev 0.887、test 0.794、全部 0.735。程式與輸出沒有改。屬 PATCH。

## 2026-11-12 — 逐鏡頭的方向把握（commit: `Show how sure each scene's direction is and mark the ones without evidence`）
- 目的：專案審視 A1：方向錯是整個鏡頭翻反，修正成本在找出是哪幾個，但沒有證據的鏡頭沒有被標出來。
- 修改：`report.direction_confidence` 依既有證據分高／中／低（無證據的鏡頭在 85 段上只有 47% 方向對，其餘 75–100%）；鏡頭表加「方向把握」欄；Web UI、CLI 摘要與預覽標出「低」的鏡頭並納入「下一個待確認」；語言包、README（中英）同步。
- 驗證：`uv run pytest` 通過（新增 3 項）；不動輸出，沒有跑驗證分數。預覽的瀏覽器顯示未驗證。屬 MINOR（新功能，鏡頭表多一欄）。

## 2026-11-12 — 連不上 AI 時改為不用 AI 並說明（commit: `Go on without the AI when its server cannot be reached`）
- 目的：專案審視 C1：沒有 AI 後端的使用者會卡在每個呼叫的重試，結果只在摘要看到一行失敗數。
- 修改：`pipeline.ai_unreachable` 開始前試連（5 秒逾時，只有連線失敗算連不上）；連不上整個流程當作 `--no-ai`，說明由 CLI 與 Web UI 顯示；語言包新增 `pipe.ai_unreachable`；README（中英）加「AI 是選用的」；ARCHITECTURE 加註。
- 驗證：`uv run pytest` 362 項通過（新增 3 項）；有 AI 時輸出不變，沒有跑驗證分數。屬 PATCH（失敗路徑的行為，介面不變）。

## 2026-11-12 — compare-runs 加上 95% 區間（commit: `Add bootstrap intervals over source series to compare-runs`）
- 目的：專案審視 B2：決定常依 ±0.005 的差異，卻沒有誤差範圍。
- 修改：`validate.py` 新增 `bootstrap_delta`，`comparison` 在每個分組下印 F1、`F1u`、`r` 變化的 95% 區間（以來源系列重抽樣）；README（中英）改 `user` 設定組的說法；DEVELOPMENT、PLAN 記錄。
- 驗證：`uv run pytest` 360 項通過（新增 2 項）。`--no-ai` 在 dev ΔF1 −0.056 [−0.097, −0.019]，在 dev2、holdout2 區間含 0。屬 PATCH。

## 2026-11-12 — 以完整重跑換掉驗證表（commit: `Replace the validation table with a full 85-clip rerun`）
- 目的：專案審視 B1／B4：驗證表混用新舊定義與日期，也不知道 AI 到底貢獻多少。
- 修改：DEVELOPMENT 的「目前的驗證結果」換成現行程式對 85 段 × default／user／noai 的同源表；舊表移到歸檔；PLAN 記錄結果。沒有改程式。
- 驗證：預設 F1 0.736（dev＋test 0.830、沒見過的 47 段 0.668）；`--no-ai` 在沒見過的 47 段 F1 同為 0.668。屬 PATCH。

## 2026-11-12 — 整理 PLAN：舊紀錄移到歸檔（commit: `Move older PLAN development log entries to the archive`）
- 目的：專案審視 D6：PLAN.md 957 行，超過一次讀檔的上限。
- 修改：2026-11-04 至 11-08 的開發紀錄原樣移到 `docs/archive/PLAN-archive.md`；更新三份文件中「歸檔從哪天以前」的說法；刪掉過時與重複的後續工作。
- 驗證：只改文件；`uv run pytest` 的檔案檢查（私人名稱、i18n）見下方執行。屬 PATCH。

## 2026-11-12 — CI 加上 ruff 檢查（commit: `Add a ruff lint job to CI`）
- 目的：專案審視 D2：CI 只跑 pytest，沒有靜態檢查。
- 修改：`pyproject.toml` 加 ruff 設定（只開 `E9`、`F`）；`tests.yml` 新增 lint job（`uvx ruff@0.17.4 check src tests`）；刪掉 tests 中 3 個沒用的匯入。
- 驗證：`uv run pytest` 358 項通過；ruff 在 src 與 tests 無發現。沒有改程式行為。屬 PATCH。

## 2026-11-12 — 快取原子寫入與文件修正（commit: `Make the AI cache atomic and fix review findings in the docs`）
- 目的：處理專案審視中小而確定的問題。
- 修改：`ai/cache.py` 原子寫入、壞檔視為沒有快取（附測試）；README／SECURITY 加上 pickle 警告；README 刪掉不符數字的「驗證分數最好」；DEVELOPMENT 補分組表並修正結構樹。
- 驗證：`uv run pytest` 通過；沒有改偵測與輸出，未跑驗證分數。屬 PATCH。

## 2026-11-12 — 專案審視：缺點與改進方向（commit: `Add a project review to PLAN: weaknesses and directions`）
- 目的：使用者要求審視整個專案，把需要改善的缺點與改進方向寫進 PLAN。
- 修改：只改文件。PLAN.md 新增「專案審視：缺點與改進方向（2026-11-12）」一節（方向的選擇、評估方法、使用門檻與產品、工程共 24 項與建議的順序）與開發紀錄條目；沒有改程式。
- 驗證：`uv run pytest` 通過；沒有跑驗證分數（沒有動偵測與輸出）。各項建議的效果未驗證。屬 PATCH。

## 2026-11-09 — 合併／分割後清除選擇的檔案（commit: `Clear the tools tab files after a merge or split`）
- 目的：使用者要求處理完後清除選擇區的檔案，不要再拿剛處理完的檔案重新辨識一次。
- 修改：`webui.py` 新增 `tool_cleared`，合併／分割成功後清空檔案框、計畫、訊息、表、預覽與按鈕（輸出的檔案保留）；README（中英）、PLAN 同步。
- 驗證：`uv run pytest` 通過；瀏覽器實測上傳模式：合併後選擇區清空、合併鈕隱藏、輸出保留、沒有再次辨識。屬 PATCH。

## 2026-11-09 — 發布步驟補上檢查每個 CI job 與標籤不可刪除（commit: `Document the release gate after the rc3 tag mishap`）
- 目的：v1.1.0rc3 在 Windows 的測試失敗時被打了標籤，而儲存庫不允許刪除標籤，只能改發 rc4。
- 修改：DEVELOPMENT.md 的發布步驟：打標籤前要確認 ubuntu 與 windows 的 job 都成功（不要把 `gh run watch` 接到 `tail`）、標籤無法重打、冒煙測試偶發失敗的處理。
- 驗證：只改文件。

## v1.1.0rc4 — 2026-11-09（預發布版）
- 新增多軸腳本支援：預覽播放器可以載入每軸一個檔案或一個檔案含多軸的腳本，每個軸在時間軸下方各顯示一條（編輯與反轉只作用於主軸）。
- 新增「工具」分頁：多軸腳本的合併與分割，放入檔案後自動判斷並先預覽；桌面版可自動帶入同資料夾的軸檔、直接輸出或另存，並可選覆蓋原檔或保留 `.backup`。
- Linux 上處理長影片時記憶體少用約三成（1 小時影片 5.1 → 3.5 GB），輸出不變。
- v1.1.0rc3 的標籤已推送但 Windows 建置在測試步驟失敗（測試的路徑處理在 Windows 上寫錯，程式沒問題），沒有發布 Release；內容與 rc3 相同，改以 rc4 發布。
- 偵測與輸出的程式碼沒有修改。Windows 版的多選檔案與拖放到新欄位尚未在實機上驗證。

## 2026-11-09 — 多軸腳本：預覽軸列與合併／分割工具（commit: `Add multi-axis script preview and the merge/split tool`）
- 目的：使用者要求預覽能顯示多軸腳本（每軸一個檔案或一個檔案含多軸），並提供合併與分割的工具。
- 修改：新增 `multiaxis.py`（辨識、合併、分割、`.backup` 安全寫檔）；預覽播放器每個軸多一條時間軸，「預覽」分頁可放入軸檔；新增「工具」分頁（自動判斷合併或分割、先預覽，桌面模式可自動帶入軸檔、直接輸出或另存、覆蓋或保留 `.backup`）；語言包、README、Windows 版說明同步。
- 驗證：`uv run pytest` 356 項通過；瀏覽器實測上傳模式的「工具」與「預覽」分頁；Windows 桌面版的選檔與拖放未驗證。不涉及偵測與輸出，沒有跑驗證分數。屬 MINOR（新功能）。

## 2026-11-09 — 長影片少用約三成記憶體，與新素材失分的診斷（commit: `Use two malloc arenas to cut memory on long videos`）
- 目的：1 小時影片的峰值記憶體 5.1 GB 且隨長度增長；研究新來源 F1 偏低的原因。
- 修改：`__init__.py` 在 Linux 把 glibc 的 malloc arena 限為 2 個（1 小時影片 5.1 → 3.5 GB，速度與輸出不變）；新增離線腳本（微調光流場 CNN、失分拆解、光流神諭等）。
- 驗證：`uv run pytest` 通過；1 小時影片輸出 10,101 個動作與修改前逐點相同；診斷、微調光流 CNN（不採用）與 render 參數在 dev2 上的重掃（仍然平坦）見 PLAN。

## 2026-11-08 — 評估端到端微調影像模型當方向線索（commit: `Evaluate a fine-tuned image network as a direction cue`）
- 目的：使用者同意試最後一個沒試過的方向：微調影像模型。
- 修改：新增 `scripts/ft_motion.py`（裁切、標籤、訓練、評估）；程式沒有改。
- 驗證：留出來源系列，|r| ≥ 0.3 的 688 個鏡頭中線索與輸出方向一致 64%（現行輸出 78%），改對 70、改錯 170；不採用。

## 2026-11-08 — 評估長鏡頭分段長度（commit: `Record the chunk length 10/30 s evaluation in PLAN`）
- 目的：不分段比 20 秒差很多，確認 20 秒是否為最佳。
- 修改：只更新 PLAN.md，程式沒有改。
- 驗證：dev＋test 28 段 F1 20 秒 0.830、10 秒 0.800、30 秒 0.800；維持 20 秒。

## v1.1.0rc2 — 2026-11-08（預發布版）
- 修正 Windows 版啟動時會閃出好幾個 cmd 視窗：設定分頁不再在啟動時查詢 Docker，只有按下 Ollama 的「執行」「檢查」「移除」才會查，而且查詢時也不會彈出視窗（尚未在 Windows 實機確認）。
- 預覽播放器重建時會記住音量。
- 偵測與輸出的程式碼沒有修改。

## 2026-11-08 — 啟動時不再查詢 Docker（commit: `Query Docker only when the user runs it`）
- 目的：使用者要求只在按下 Docker 模式的一鍵執行時才執行 `docker info`。
- 修改：預設模式與選項提示改用 `docker_installed()`（只檢查指令是否存在）；移除上一筆加的 30 秒快取。
- 驗證：`uv run pytest` 全部通過。

## 2026-11-08 — 修正 Windows 版啟動時彈出多個 cmd 視窗（commit: `Hide console windows of docker and git calls on Windows`）
- 目的：Windows 版啟動時會閃出好幾個 cmd 視窗。
- 修改：新增 `subproc.py`（Windows 上子程序不開主控台視窗），`docker`、`git` 的呼叫改用它；`docker info` 的結果快取 30 秒，不再每次建立畫面都重查。
- 驗證：`uv run pytest` 全部通過；Windows 實機上視窗是否消失尚未驗證。

## 2026-11-08 — 記錄長鏡頭沿用前一段 AI 分析的評估（commit: `Record the chunk AI reuse evaluation in PLAN`）
- 目的：使用者要求試「長鏡頭的後段沿用前一段的 AI 區域與方向」。
- 修改：沒有改程式；PLAN 加評估紀錄與已放棄的方案。實驗用的選項與設定已移除。
- 驗證：28 段 default 平均 F1 0.830（基準）對 0.817–0.820，`F1u` 0.842 對 0.837–0.840，不採用。


## 2026-11-08 — 記錄長鏡頭分段一致性的評估（commit: `Record the chunk consistency evaluation in PLAN`）
- 目的：使用者說有些鏡頭其實相同卻被切成好幾段，想知道有沒有辦法讓它們一致。
- 修改：沒有改程式；PLAN 加評估紀錄。實驗用的選項與設定已移除。
- 驗證：28 段 default 平均 F1 0.830；相鄰分段共用節奏 0.828–0.829、共用行程大小 0.825，都不採用。

## 2026-11-08 — 記錄長鏡頭不分段的評估（commit: `Record the no-chunk evaluation in PLAN`）
- 目的：使用者問長鏡頭為什麼預設每 20 秒切一段，並要求沒差多少就預設關閉。
- 修改：沒有改程式；PLAN 加評估紀錄與已放棄的方案。實驗用的 `--max-chunk` 選項已移除。
- 驗證：28 段 default 平均 F1 0.830（20 秒）對 0.783（不分段），F01 −0.361、A03 −0.159；不分段時 E01 一支用 2.9 GB 記憶體。結論是維持 20 秒。

## 2026-11-08 — 預覽播放器記住音量（commit: `Keep the preview player volume across rebuilds`）
- 目的：預覽中按反轉或儲存編輯後，播放器重建，音量被重設為最大。
- 修改：`preview.py` 把音量與靜音存在 `localStorage`，新播放器讀回（和播放速度相同做法）；`tests/test_preview.py` 加一項測試。
- 驗證：`uv run pytest` 327 passed、2 skipped；用 Chromium 載入兩次確認音量與靜音保留。

## v1.1.0rc1 — 2026-11-08（預發布版）
- Windows 版直接讀取本機檔案：「產生」「批次」「預覽」都可以拖放或選取檔案，不再上傳；預覽分頁新增開關，選了影片或 funscript 後自動帶入同資料夾同名的檔案。
- Windows 版改用 PyInstaller 建置：解壓縮後約 3,200 個檔案（原本 28,000 多個），zip 約 240 MB；視窗先顯示載入頁，不必等伺服器啟動。
- 偵測與輸出的程式碼沒有修改（只動到桌面版與 Web UI）。

## 2026-11-08 — Windows 版改用 PyInstaller 建置（commit: `Build the Windows version with PyInstaller only`）
- 目的：PyInstaller 版在 Actions 上建置通過、桌面視窗也確認正常，取代附完整 Python 的建置（15,874 個檔案）。
- 修改：`build-pyinstaller.ps1` 改名 `build.ps1`（取代舊的）；刪除 `launcher.cs`、`smoke_ui.py`；`smoke-test.ps1` 只支援這一種配置（`-Python` 必填）；`windows.yml` 拿掉 `builder` 選項；DEVELOPMENT、PLAN 同步。
- 驗證：Actions（`0b7a9d6`）單元測試 323 passed，建置 3,199 個檔案、538 MB、zip 240 MB，冒煙測試通過；改名後的腳本在 testhost 重跑：建置 3,154 個檔案、539 MB、zip 239 MB，冒煙測試通過；`uv run pytest` 326 passed、2 skipped。

## 2026-11-08 — Windows 版的 PyInstaller 試作（commit: `Add a PyInstaller build of the Windows version`）
- 目的：把檔案數降到一兩千個級別；使用者同意先試作。
- 修改：新增 `build-pyinstaller.ps1`、`pyinstaller/funscript-gen.spec`、`pyinstaller/entry.py`；`smoke-test.ps1` 支援沒有 Python 的資料夾（`-Python`）；`windows.yml` 的手動執行加 `builder` 選項（預設仍是原本的建置）。
- 驗證：testhost 上 3,153 個檔案、539 MB、zip 239 MB、解壓縮 2.3 秒（原本 15,874 個、7.6 秒）；冒煙測試通過；用瀏覽器對打包版走過產生與預覽。真實桌面視窗與 Actions 上未驗證。

## 2026-11-08 — Windows 版只放使用者用的檔案（commit: `Leave developer files out of the Windows build`）
- 目的：使用者要求發行版只放執行時用得到的，不放開發者用的。
- 修改：`build.ps1` 再刪 `Scripts\` 的命令列 exe、C／Cython 檔與靜態庫、onnxruntime 的轉換工具；保留 Gradio 的 `.pyi`（它每次匯入都會重寫）；`numpy.f2py` 不能刪（scipy 會碰它）。
- 驗證：testhost 建置，15,874 個檔案、650 MB，冒煙測試通過。

## 2026-11-08 — Windows 版瘦身與加快開啟（commit: `Slim the Windows build and open its window first`）
- 目的：解壓縮後有 28,000 多個檔案、開啟緩慢。
- 修改：`build.ps1` 排除 sympy／mpmath 並刪掉測試、pip、Tcl/Tk、SSR node 應用、型別檔；`FunscriptGen.exe` 改執行 `funscript_gen.app`，視窗先顯示載入頁、伺服器在執行緒中啟動；冒煙測試加入 Web UI 步驟。
- 驗證：檔案 28,618 → 16,782、zip 313 → 246 MB、解壓縮 12.2 → 7.6 秒、伺服器可連線 5.06 → 4.54 秒（testhost）；冒煙測試與 `uv run pytest`（326 passed）通過。視窗的載入頁在真實桌面上未驗證。

## 2026-11-08 — 桌面版直接讀取本機檔案，預覽可自動帶入同名檔案（commit: `Read local files directly in the desktop app`）
- 目的：Windows 版（桌面模式）不再上傳，產生、批次、預覽三個分頁都直接讀取本機檔案；預覽分頁選了影片或 funscript 後可以自動帶入同資料夾的同名檔案。
- 修改：`webui.py`（路徑框、拖放區、`dropped`／`sibling`、預覽的「自動帶入同名的檔案」開關）、`app.py`（拖放處理、選擇 funscript 的對話框）、語言包、文件；修好「選擇…」按鈕從未顯示的問題。
- 驗證：`uv run pytest` 322 passed；headless Chromium 驗證拖放流程。Windows 實機視窗的拖放與選檔對話框未驗證。

## 2026-11-08 — 先停止改進，更新 README 的準確度與已知問題（commit: `Document the accuracy on unseen sources in the readmes`）
- 目的：使用者決定先停在這裡；把新素材上量到的實際準確度與限制告訴使用者。
- 修改：README.zh.md、README.md（準確度改為 85 段、新來源約 0.67；已知問題補上節奏不明顯的快行程鏡頭），DEVELOPMENT.md 與 PLAN.md 記錄決定與技術細節；未改程式。
- 驗證：未改程式。`uv run pytest` 通過。

## 2026-11-08 — 網格區域搜尋的實驗（commit: `Record the grid region search experiment`）
- 目的：依使用者選的方向，為無節奏的快行程鏡頭保留多個區域的光流，採用節奏最清楚的區域。
- 修改：新增 `scripts/region_oracle.py`（離線）；PLAN 記錄結果；主程式未改（臨時的實驗程式碼已還原）。
- 驗證：上限很高（依集中度挑的 |r| 中位數 0.74，使用的區域 0.42，機率水準 0.39），但新區域的方向只有一半和人工腳本同向；完整流程 dev2 F1 −0.009（`F1u` +0.026）、舊 28 段 −0.006、holdout2 −0.002，不採用。`uv run pytest` 通過。

## 2026-11-08 — 無節奏鏡頭改用 Hybrid 測量的實驗（commit: `Record the Hybrid measurement splice experiment`）
- 目的：Hybrid 在 default 量不到動作的鏡頭上較好，檢查逐鏡頭選用它能不能提高整體分數。
- 修改：新增 `scripts/splice_scenes.py`（離線）；PLAN 記錄結果；主程式未改（臨時的閘門實驗已還原）。
- 驗證：逐鏡頭拼接 dev2 F1 +0.018、舊 28 段 +0.002、holdout2 +0.007，在雜訊內且要跑兩條流程；Hybrid 內部閘門 dev2 `F1u` −0.006，不採用。`uv run pytest` 通過。

## 2026-11-08 — 新素材的 user 基準與行程率線索研究（commit: `Record the user baseline and the stroke-rate cue study`）
- 目的：依使用者同意的三項後續，補 `user` 設定在新素材上的基準，並研究無節奏鏡頭漏掉行程的原因。
- 修改：新增 `scripts/freq_cues.py`、`scripts/peak_cue.py`（離線）；PLAN、DEVELOPMENT 記錄結果；主程式未改。
- 驗證：`user` 在 47 段新素材 F1 0.658（`F1u` 0.722，default 0.668／0.711）；行程率線索都對不上人工腳本（7–27%），神諭頻率只多 +0.017，瓶頸是光流沒量到；有監督的方向模型沒有執行（見 PLAN）。`uv run pytest` 通過。

## 2026-11-07 — 新增 47 段驗證素材與泛化基準（commit: `Add 47 validation clips and record the generalisation baseline`）
- 目的：使用者補充 valid/ 的素材；用沒調過規則的來源量現行程式的泛化程度，並重新檢驗高通後備。
- 修改：`validation.toml` 新增 `dev2`（22 段）與 `holdout2`（25 段）；PLAN、DEVELOPMENT、CLAUDE.md 記錄分組與結果；主程式未改。
- 驗證：新素材 default 平均 F1 0.668（dev＋test 是 0.830），`F1u` 0.711，主要失分是沒有節奏的鏡頭漏掉行程；高通後備在 dev2 +0.016，holdout2 −0.004（`F1u` −0.014），不採用。`uv run pytest` 通過。

## 2026-11-07 — 查證 D03 的低召回率（commit: `Record the D03 low-recall analysis`）
- 目的：確認 D03 召回率 0.41 是不是節奏濾波鎖到次諧波，並盤點剩下的研究方向。
- 修改：只改 PLAN.md（未改程式）。D03 的差距來自人工腳本每個行程頂端多寫的小抖動與疊在慢速漂移上的 5 Hz 小行程（兩者都已有紀錄）；剩下的方向都需要使用者決定。
- 驗證：未改程式。

## 2026-11-07 — 特徵差預測方向實驗（commit: `Record the feature-difference direction experiment`）
- 目的：用相鄰幀的凍結特徵差（而不是單幀）預測人工腳本的速度方向，補現行方向判斷的缺口。
- 修改：新增 `scripts/depth_motion.py`（離線），更新 PLAN.md；主程式未改。
- 驗證：215 個鏡頭一致率最高 75–77%，現行輸出 84%，改錯多於改對，不採用。

## 2026-11-07 — 23.976 fps 與一拍二的穩健性驗證（commit: `Check robustness to 24 fps and animation on twos`）
- 目的：驗證集沒有一般動畫的 23.976 fps，確認幀率與一拍二（12 fps 動作）是否造成問題。
- 修改：新增 `scripts/make_variants.py`（重新編碼出變體素材），更新 PLAN.md；主程式未改。
- 驗證：與同幀率重新編碼的雜訊（`F1u` −0.007）相比，23.976 fps 沒有差別，一拍二 `F1u` 再低約 0.012，只影響每秒超過約 4 Hz 的快速素材；不處理。

## 2026-11-07 — VLM 框選部位實驗（commit: `Record the VLM part box experiment`）
- 目的：以 Qwen3-VL-8B 逐幀框陰莖與陰部，補上部位偵測器缺的方向證據。
- 修改：新增 `scripts/vlm_parts.py`（離線），更新 PLAN.md；主程式未改。
- 驗證：33 個有距離的鏡頭正負號一致 15 個（隨機水準），G 系列幾乎拿不到距離，不採用。

## 2026-11-07 — RAFT 光流實驗（commit: `Record the RAFT optical flow experiment`）
- 目的：確認低相關鏡頭是否因 Farneback 沒量到動作，學習式光流能否改善。
- 修改：新增 `scripts/raft_compare.py`（離線比較），更新 PLAN.md；主程式未改。
- 驗證：51 個低相關鏡頭平均 |r| Farneback 0.334、RAFT-small 0.320，贏輸各半、慢 8 倍，不採用。

## 2026-11-07 — Farneback 視窗大小實驗（commit: `Record the Farneback window size experiment`）
- 目的：確認低相關鏡頭是否因光流參數。
- 修改：只更新 PLAN.md（程式未改）。
- 驗證：winsize 31／13 的 `F1u` 0.842 → 0.836／0.838，持平，不採用。

## 2026-11-06 — 素材資料夾改名為 valid（commit: `Rename the vaild clips folder to valid`）
- 目的：資料夾名稱是拼錯字。
- 修改：`vaild/` 改為 `valid/`，同步更新 `.gitignore`、`validation.toml`、`validate.py` 預設值、`scripts/` 路徑與 DEVELOPMENT.md；testhost 也一併改名。
- 驗證：`uv run pytest` 319 通過、2 略過；未改演算法。

## 2026-11-06 — 記錄暫不使用 INT8 部位框模型（commit: `Record the decision to keep the FP32 part detector`）
- 目的：記下使用者的決定。
- 修改：只改 PLAN.md：INT8 量化從後續工作移到已放棄的方案（暫不使用），開發紀錄註明決定。
- 驗證：未改程式，`uv run pytest` 通過。

## 2026-11-06 — 部位框模型 INT8 量化的離線實驗（commit: `Record the INT8 part detector experiment`）
- 目的：部位框在 CPU 上是最大的瓶頸，評估量化能快多少、會不會改變輸出。
- 修改：只改 PLAN.md；靜態 INT8（偵測頭保留 FP32、`reduce_range`）CPU 上快 1.9–2.5 倍，不同 CPU 逐幀相同。
- 驗證：dev＋test 28 段中 27 段逐點相同，I01 一個長鏡頭方向變錯（F1 −0.008）；未改程式，`uv run pytest` 通過。

## 2026-11-06 — 重算小行程漏掉的比例（commit: `Re-measure missed small strokes`）
- 目的：決定要不要做殘差轉折點補點。
- 修改：只改 PLAN.md；用 `scripts/missed_points.py` 離線重算，真的漏掉的行程約 dev 7%、test 9%，上限小，不做。
- 驗證：未改程式，未跑素材驗證。

## 2026-11-06 — Docker 與 Windows 版的說明也改以英文版為主（commit: `Make the English Docker and Windows readmes the default`）
- 目的：和專案 README 一致：沒有後綴的是英文版，繁體中文版加 `.zh`。
- 修改：`docker/README.md`（英文）／`docker/README.zh.md`；`packaging/windows/README.txt`（英文）／`README.zh.txt`，`build.ps1` 放進 zip 的檔名跟著改；更新語言切換與 README、DEVELOPMENT、compose 檔中的連結。
- 驗證：`uv run pytest` 通過；GitHub Actions 的 Windows 建置通過，zip 內是 `README.txt` 與 `README.zh.txt`。

## 2026-11-06 — README 改以英文版為主（commit: `Make the English README the default`）
- 目的：GitHub 首頁顯示英文說明。
- 修改：`README.en.md` → `README.md`（英文），原 `README.md` → `README.zh.md`（繁體中文）；更新兩份的語言切換連結、`docker/README*.md`、ARCHITECTURE、DEVELOPMENT 的連結；v1.0.0 Release 說明的連結。`pyproject.toml` 的 `readme` 因此變成英文版。
- 驗證：`uv run pytest` 通過；只改文件。

## 2026-11-06 — 記錄 Pillow 安全警告的處理方式（commit: `Document the pending Pillow security alerts`）
- 目的：Dependabot 對 Pillow 12.3.0 回報 41 個警告，修正版 13.0.0 被 gradio 的 `pillow<13` 擋住。
- 修改：PLAN 的後續工作記下風險評估（程式不開啟外來的圖檔）與決定（等 gradio 放寬，不強制 override）。
- 驗證：只改文件。

## 2026-11-06 — 更新 Dependabot 提出的相依套件（commit: `Update gradio, openai, huggingface-hub, torch and ultralytics`）
- 目的：處理 Dependabot 的 PR #4–8。
- 修改：`uv.lock`：gradio 6.31.0、openai 3.42.1、huggingface-hub 2.4.0、torch 2.15.0、ultralytics 8.4.199，torchvision 一併升到 0.29.2（和 torch 2.15 配對）。
- 驗證：`uv run pytest` 319 passed；同一份程式碼新舊套件各跑一次驗證，28 段的動作逐點相同（dev F1 0.853、test 0.799）；Web UI 在瀏覽器中正常、骨架模式合成影片 F1 0.98。

## 2026-11-06 — 記錄 v1.0.0 的發布（commit: `Record the v1.0.0 release in PLAN`）
- 目的：記下發布的結果與 repo 設定。
- 修改：PLAN 的開發紀錄與後續工作（簽章、圖示、Dependabot 的相依套件 PR）。
- 驗證：只改文件。

## v1.0.0 — 2026-11-06（第一個公開版本）
- 從影片產生 funscript：光流追蹤兩人的相對動作，AI（Qwen3-VL，vLLM 或 Ollama）判斷每個鏡頭的互動區域與方向，部位框輔助判斷高低。
- CLI、Web UI、Windows 免安裝版（圖形介面與指令）、Docker；繁體中文與英文介面。
- 授權：PolyForm Noncommercial 1.0.0（禁止商業使用）。

## 2026-11-06 — GitHub Actions 的 action 升級到 Node 24 版（commit: `Update GitHub Actions to Node 24 releases`）
- 目的：GitHub 警告 `checkout@v4`、`setup-uv@v6`、`upload-artifact@v4` 用的 Node.js 20 已停止支援（Dependabot 的 PR #1–3）。
- 修改：`tests.yml`、`windows.yml` 改用 `actions/checkout@v7`、`astral-sh/setup-uv@v7`、`actions/upload-artifact@v7`；`uv` 版本維持 0.11.19（和 Dockerfile 相同）。
- 驗證：GitHub Actions 的 Tests 與 Windows portable 結果見 PLAN。

## 2026-11-06 — 文字檔一律以 UTF-8 讀寫（commit: `Open text files as UTF-8 on every platform`）
- 目的：GitHub Actions 的英文 Windows（cp1252）上 2 個測試失敗：沒指定編碼的讀寫用系統字碼頁，寫不出中文（`.webui-last.json`、驗證的記錄），`.funscript` 的中文備註也會受影響；免安裝版以 `-X utf8` 執行所以沒遇到。
- 修改：`src/` 中 19 處 `read_text`／`write_text`／`open` 加 `encoding="utf-8"`（讀 `.funscript` 用 `utf-8-sig`，接受 BOM）；`validate` 的子程序設 `PYTHONUTF8=1`；新增 `tests/test_encoding.py`（以 AST 檢查沒有遺漏）。
- 驗證：本機 `uv run pytest` 319 passed；GitHub Actions 的 Windows 結果見 PLAN。

## 2026-11-06 — 第一個公開版本 v1.0.0（commit: `Release v1.0.0`）
- 目的：在 GitHub 公開發布第一版，訂出版本編碼原則。
- 修改：版本號改為 1.0.0，只寫在 `__init__.py`（`pyproject.toml` 改用 hatch 動態讀取）；`pyproject.toml` 加 `[project.urls]`；README 中英文版的下載連結指向 Releases；DEVELOPMENT 新增「版本與發布」（SemVer、公開介面、發布步驟），CONTRIBUTING 加版本一節；CHANGELOG 加版本標題；`scripts/check_history.py` 可以只檢查指定的分支與標籤。
- 驗證：`uv run pytest` 通過；wheel 的版本是 1.0.0。只改版本與文件，未跑素材驗證。

## 2026-11-06 — 記錄陰莖框大小判斷方向的評估（commit: `Document penis box size direction experiment in PLAN`）
- 目的：評估「框越大＝向上」及只在兩框同時移動的鏡頭使用，能否補強部位框距離。
- 修改：新增離線腳本 `scripts/box_size.py`；PLAN.md 記錄評估與已放棄的方案；主程式沒有改。
- 驗證：`uv run pytest` 通過；離線模擬反轉規則改對 3、改錯 3（距離 1、0），結論不採用。

## 2026-11-06 — 新增偵測模型檢視器（開發者用）（commit: `Add detection model viewer script for developers`）
- 目的：讓開發者比較各偵測模型在某一幀或整支影片上抓到的框，以及 VLM 的人物框與互動區域。
- 修改：新增 `scripts/detect_viewer.py`（Gradio，不加入主程式與 CLI）；用法寫在 DEVELOPMENT.md；PLAN.md 更正部位框模型升級的候選（沒有更大的 censor 規格）。
- 驗證：`uv run pytest` 通過；腳本的偵測、掃描、VLM 路徑各跑過一次。

## 2026-11-06 — 記錄人物偵測器取代 VLM 人物框的實驗（commit: `Document person detector experiment result in PLAN`）
- 目的：評估用動漫人物偵測器取代 VLM 的人物框是否改善分析區域。
- 修改：只留下紀錄（`PLAN.md` 開發紀錄與已放棄的方案）；實驗程式已移除。
- 驗證：dev＋test 28 段 F1 0.830 → 0.815、`F1u` 0.842 → 0.841，沒有進步，不採用。

## 2026-11-06 — 記錄部位框偵測模型升級與擴充計畫（commit: `Document part detector model upgrade plan in PLAN`）
- 目的：將部位框偵測模型的升級方向（同系列較大規格模型、擴充口／手／3D 畫風的多部位 YOLO 模型）記入後續工作。
- 修改：`PLAN.md`「尚未完成的後續工作」新增「部位框偵測模型升級與擴充」。
- 驗證：只改文件；`uv run pytest` 通過。

## 2026-11-06 — ARCHITECTURE 也改用中性詞（commit: `Use neutral terms in ARCHITECTURE`）
- 目的：延續上一筆，流程圖與表格的露骨用詞也改掉。
- 修改：ARCHITECTURE.md 的用詞改為主動部位、前端、目標區域等；DEVELOPMENT.md 的「對外用詞對照」同步（ARCHITECTURE 列入中性詞範圍，檢查指令加上它）。
- 驗證：只改文件；`uv run pytest` 通過。

## 2026-11-06 — 使用者看得到的文字改用中性詞（commit: `Use neutral terms in user-facing text and document the mapping`）
- 目的：專案公開前，README、UI、語言包的露骨用詞改為中性詞；程式識別字、AI 提示詞、開發紀錄維持原詞。
- 修改：README／README.en、`lang/zh-TW.toml`、`lang/en.toml`（`_template.toml` 重新產生）、`options.py` 的 CLI 說明、`report.py` 的「target」標籤；DEVELOPMENT.md 新增「對外用詞對照」，說明每個中性詞原先代表什麼。
- 驗證：`uv run pytest` 317 通過（兩個測試的斷言文字跟著改）；只改文字，未跑驗證素材。

## 2026-11-06 — 改為禁止商業使用的授權並補 GitHub 文件（commit: `Relicense to PolyForm Noncommercial and add GitHub project files`）
- 目的：公開前的合規：整個專案禁止商業使用，補上 GitHub 慣用的文件與設定，`CLAUDE.md` 不再提交。
- 修改：`LICENSE` 改為 PolyForm Noncommercial 1.0.0；README、THIRD_PARTY_NOTICES、Windows 版說明同步（imgutils 的 MIT 條文、NudeNet、商用注意事項）；新增 SECURITY.md、CONTRIBUTING.md、issue／PR 範本、dependabot、tests.yml、.gitattributes、`scripts/check_history.py`。
- 驗證：`uv run pytest` 通過；`check_history.py` 在現有歷史找到 20 種真實名稱，發布時要以全新的單一 commit 當第一版。只改文件與設定，未跑素材驗證。

## 2026-11-06 — 設定分頁的區塊預設收合（commit: `Collapse settings tab sections by default`）
- 目的：設定分頁打開時各區塊都展開，太長
- 修改：`webui.py` 設定分頁的「AI API」、運算裝置、輸出檔管理三個區塊改為預設收合（產生分頁不變）
- 驗證：`uv run pytest` 317 通過（只改 UI 預設狀態，不影響偵測，未跑驗證素材）

## 2026-11-06 — 一鍵 Ollama 的確認狀態與清除（commit: `Add Ollama status check and removal buttons`）
- 目的：能查看目前的 Ollama 狀態，並清掉自動建立的 Docker 資源。
- 修改：ollama_setup.py 加 `status`、`remove_docker`；設定分頁加「確認狀態」「清除自動安裝的 Ollama」（清除需再確認）；語言包、測試、README、PLAN。
- 驗證：`uv run pytest` 通過；真的刪除容器未驗證。

## 2026-11-06 — 一鍵 Ollama 保留金鑰並隨程式關閉（commit: `Keep API key and stop started Ollama on exit`）
- 目的：切到一鍵 Ollama 不該丟掉原本的 API 金鑰；程式結束時不該留下自己啟動的 Ollama。
- 修改：ollama_setup.py 記錄自己啟動的容器與 `ollama serve`，在 `launch` 結束與 atexit 時停止（容器只 stop 不刪除，不再設 restart policy）；run_ollama 不再清金鑰；測試、README、PLAN。
- 驗證：`uv run pytest` 通過；實際關閉行為未用真的 Docker／Ollama 驗證。

## 2026-11-06 — 設定分頁一鍵執行 Ollama（commit: `Add one-click Ollama setup to the settings tab`）
- 目的：選 Ollama 時不必自己架設，就能在本機啟動並接上。
- 修改：新增 ollama_setup.py 與設定分頁的「一鍵執行」區（選 Docker 或已安裝的 Ollama、選模型，自動啟動、下載並把設定指向它）；語言包、測試、README、PLAN。
- 驗證：`uv run pytest` 通過；實際啟動 Docker／下載模型未驗證。

## 2026-11-06 — 部位框推論等確認有人再啟動（commit: `Start part detection after the scene analyses`）
- 目的：片頭的空鏡頭會先占滿部位框推論的 CPU 執行緒。
- 修改：pipeline.py 的 `PartScan` 加 `defer`／`start()`，`plan_scenes` 加 `on_seen` 回呼；使用 AI 時只排入看得到人的鏡頭；測試、PLAN、ARCHITECTURE。
- 驗證：`uv run pytest` 通過；28 段輸出與修改前逐點相同；D02 沒有快取時 79.4 → 75.0 秒（單次）。

## 2026-11-06 — 銜接補點維持現狀（commit: `Record decision to keep bridge parameters internal`）
- 目的：整理待辦中的 `bridge_max`、`bridge_tol`。
- 修改：PLAN 移除該待辦，並在「已放棄的方案」記下不開放設定、不改成一律照抄的原因。程式未改。
- 驗證：文件修改，未跑測試與驗證集。

## 2026-11-06 — 更新 --no-ai 基準分數（commit: `Refresh --no-ai baseline scores`）
- 目的：DEVELOPMENT.md 的「不用 AI」兩列還是 2026-11-02 的舊數字。
- 修改：DEVELOPMENT.md 兩列改為 `out/runs/noai1106` 的數字；PLAN 加紀錄並移除該待辦。程式未改。
- 驗證：dev 原 13 段 F1 0.748 → 0.825、test 0.716 → 0.733；原因未逐項拆解。

## 2026-11-05 — 預覽分頁加入不切分鏡頭與取消載入（commit: `Add scene-less preview and cancel to the preview tab`）
- 目的：預覽載入的進度條與數字不同步；長片載入時無法中止，也沒有略過鏡頭偵測的選項。
- 修改：webui.py 進度每 1% 更新一次；新增「不切分鏡頭預覽」「取消載入」按鈕；語言包、README（中英）、測試。
- 驗證：`uv run pytest` 302 通過；進度條落後是否已消除未用瀏覽器驗證。

## 2026-11-05 — 評估女性部位錨點的方向判斷（commit: `Evaluate female-part anchors for stroke direction`）
- 目的：使用者提議抓不到陰莖框時，以女性部位（陰道、手、口、乳頭）加附近光流最強處的距離判斷行程方向。
- 修改：新增 `scripts/female_anchor.py`（離線評估）；PLAN 記錄結論；主程式未改。
- 驗證：`uv run pytest` 通過；沒有陰莖框的 120 個鏡頭中，線索和人工腳本同向的比例 2D dev 10–14／32、G 23–29／53–55，所有變體的 dev F1 都不高於現行（0.851），結論：不採用。

## 2026-11-05 — 低光流忽略規則只對 G 系列套用（commit: `Apply the low-flow ignore rule to the G series only`）
- 目的：門檻降到 1 後規則對 G 系列沒作用；改回 2，並限定 G 系列，避免 E01 這類有小動作的素材被忽略。
- 修改：`validate.LOW_FLOW_STD` 回到 2；`score(..., ignore_low_flow)`，`validation.toml` 新增 `ignore_low_flow = [G01…G07]`；執行器與 `scripts/rescore_run.py`、`score_external.py` 依代號傳入；測試與文件同步。
- 驗證：`uv run pytest` 通過；default dev 0.853、test 0.799（不忽略 0.851／0.799）；G06 +0.021、G04 +0.008；G 以外的素材分數不變。

## 2026-11-05 — 忽略門檻降到光流標準差 1（commit: `Lower the low-flow ignore threshold to 1`）
- 目的：E01 開頭四個有小動作的鏡頭（標準差 1.3–1.7）被忽略了 66 秒，使用者指正要提高門檻。
- 修改：`validate.LOW_FLOW_STD` 2 → 1；DEVELOPMENT 與 PLAN 的數字更新。
- 驗證：`uv run pytest` 通過；default dev 0.852、test 0.800（不忽略 0.851／0.799）；E01 不再被忽略；規則對 G 系列幾乎不再有作用。

## 2026-11-05 — 評分忽略光流很低且沒有部位框的鏡頭（commit: `Skip unjudgeable stretches when scoring`）
- 目的：G 系列等人工腳本中作者依音樂加的行程，畫面看不出來，不計入評分。
- 修改：debug 資料加 `parts_found`；`validate.py` 新增 `ignore_spans`（光流標準差 < 2 且沒有部位框的鏡頭），`evaluate.compare(ignore=...)` 排除這些時間內兩邊的轉折點；`f1_noign` 保留舊值；測試與文件同步。
- 驗證：`uv run pytest` 通過；套用到所有素材（G 以外 24 段平均沒有下降）：default dev 0.851 → 0.858、test 0.799 → 0.797；G 系列 0.737 → 0.745。個別下降：H02 −0.024、D01 −0.011、A03 −0.008。

## 2026-11-05 — 查證 A06 開頭節奏錯的原因（commit: `Record the A06 tempo investigation`）
- 目的：使用者要求查 A06 開頭 10 秒輸出頻率與人工腳本不同的原因。
- 修改：新增 `scripts/tempo_windows.py`（比較輸出與人工腳本在 5 秒窗口的主頻），更新 PLAN 與 DEVELOPMENT；程式未改。
- 驗證：`uv run pytest` 通過；原因是選中的區域是 2.5 Hz，人工腳本跟的小塊是 1.5 Hz；dev＋test 窗口中 80% 頻率吻合、17% 不符，A06 只佔 3 個，不為單一鏡頭改區域選擇。

## 2026-11-05 — 評分忽略人工腳本的顫動（commit: `Ignore tremble runs in the simplified hand-made script`）
- 目的：A06 等人工腳本中有作者額外加的 5–6 Hz 小顫動（畫面看不出來），評分時忽略。
- 修改：`evaluate.simple_extrema` 把連續三點以上、擺幅 ≤ 10、間隔 ≤ 200 ms、整段範圍 ≤ 20 的顫動合併成一個停頓（只對人工腳本）；新增 `scripts/list_mismatches.py` 列出沒配到的點；測試與文件同步。
- 驗證：`uv run pytest` 通過；動作逐點相同，只有量尺不同：default dev 0.790 → 0.851、test 0.755 → 0.799、holdout 0.723 → 0.788；A06 漏掉 69 → 29。
- 注意：被合併的占 38 段人工點的 20%，B03／D02 的 F1 因此大幅上升（間隔約一個影格的雜訊點）。

## 2026-11-05 — 評分改用簡化後的人工腳本（commit: `Score against a simplified hand-made script`）
- 目的：K01、A06、B04 的人工腳本在同一方向的行程中途有很多只改變速度的點（小回跳、停頓兩端各算一個），讓 F1 偏低；評分時忽略它們。
- 修改：`evaluate.py` 新增 `simple_extrema` 與 `compare(simplify=True)`（停頓合成一點、小於較小鄰近擺幅 0.3 倍的行程中途反向不算轉折點）；`validate.py` 的 F1 改為簡化版，舊值存為 `f1_raw`；新增 `scripts/rescore_run.py` 重算既有的執行；測試與 README、DEVELOPMENT、PLAN 同步。
- 驗證：`uv run pytest` 299 passed；動作逐點相同，只有量尺不同：default dev 0.756 → 0.790、test 0.737 → 0.755、holdout 0.668 → 0.723；K01 +0.107、B04 +0.068。
- 注意：這是量尺改變，不是進步；之後和 `*-simple` 基準比較。

## 2026-11-05 — 評估補點前檢查下一個鏡頭的動量（commit: `Record the bridge next-scene momentum evaluation`）
- 目的：避免鏡頭切換後新鏡頭一開始就放慢或停頓時仍補點（N01）。
- 修改：試作後還原，只更新 PLAN（結論：dev＋test 沒有淨增益）。
- 驗證：`uv run pytest` 298 passed；28 段 default F1 0.748 → 0.748（門檻 1.5／2／3 皆同），user 0.743 → 0.742。

## 2026-11-05 — 評估短鏡頭放寬部位框檢查（commit: `Record the short-shot part check evaluation`）
- 目的：嘗試讓 G 系列的 1–2 秒鏡頭也能用部位框判斷方向。
- 修改：試作後還原，只更新 PLAN（結論：無效，G03／G06 的短鏡頭偵測不到陰莖框）。
- 驗證：`uv run pytest` 298 passed；28 段 default F1 0.743 → 0.743，27 段逐點相同。

## 2026-11-05 — 評估移除或重建行程範圍辨識與整理待處理改進項目（commit: `Record the stroke-range evaluation and pending improvements`）
- 目的：使用者要求評估移除或重建行程範圍辨識（`--stroke-range`）對分數的影響，並將其餘改進方向記錄為待處理項目。
- 修改：只更新 PLAN 與 DEVELOPMENT（記錄行程範圍辨識在 28 段素材上的統計、移除與多種重建方案的分數比較，以及待處理的改進項目）；依使用者決定維持主程式不變。
- 驗證：未改程式，`uv run pytest` 298 passed。28 段 367 個有效鏡頭中 AI 有 311 個（85%）判看不到龜頭（18 段整支與固定截到 80 逐點相同）；完全移除時 `default` F1 持平（dev 0.756、test 0.737）、r 略降（0.557 → 0.551），`user` 在 test 上 F1 0.734 → 0.739、r 0.563 → 0.568；不呼叫 AI 固定截到 80 時各組分數與現行幾乎相同。

## 2026-11-05 — 快慢判斷：聲音沒有反對就用較低門檻（commit: `Lower the asymmetry threshold unless the sound vetoes`）
- 目的：使用者要求不用 2D／3D 標籤，改找其他特點來決定快慢門檻何時可以放低。
- 修改：`pipeline.flip_by_asymmetry` 的門檻在有聲音、且撞擊聲不在低點時用 `asym_audio_threshold`（0.2），起點在低點時線性升回 0.5，沒有聲音時維持 0.5（原本只有起點在高點才降低）；備註只在聲音明確在高點時提到聲音。`options.py`、語言包的說明，`tests/test_chunks.py` 新增 1 個測試，新增 `scripts/asym_threshold_sim.py`；PLAN、DEVELOPMENT、ARCHITECTURE 更新。
- 驗證：`uv run pytest` 298 passed；`--replay`：預設 dev F1 0.747 → 0.756、test 0.724 → 0.737、holdout 0.661 → 0.668（`F1u` 不變），`--preset user` dev 0.739 → 0.749、test 0.735 → 0.734；G 系列與 I01 改善，F01 −0.06。

## 2026-11-05 — 評估依鏡頭類別分別判斷方向（commit: `Record the per-category direction evaluation`）
- 目的：使用者詢問能否以 AI 或分類器替鏡頭分類，再對特定類別用特定方式判斷。
- 修改：只更新 PLAN（開發紀錄、已放棄的方案、3D 門檻的後續工作）；試做的 AI 畫風判斷與 `--art-style` 未提交（放在 `git stash`）。
- 驗證：未改程式，`uv run pytest` 297 passed。方向的剩餘錯誤 2D 只有 10 個鏡頭、G 系列 87 個；Qwen3-VL-8B 判畫風在 28 段只對 5–10 段，`anime_classification` 38 段全部判成 3D，分不出 G 系列。

## 2026-11-05 — 改進行程方向對齊與判斷（commit: `Improve stroke direction alignment and flip checks`）
- 目的：使用者要求針對方向判斷增強辨識正確率。
- 修改：`pipeline.py` 的 `_cosine` 在兩分段重疊區域 ≥ 4 格且雙邊重疊能量密度達平均 0.3 倍時，改用全長與重疊長度的幾何平均標準化餘弦，避免同鏡頭不同大小 ROI 的對齊被非重疊區稀釋；`align_chunks` 的錨點改以 `sign_margin × 有效格數 × 位移幅度`（`_anchor_weight`）選擇；`flip_by_parts` 改為將同鏡頭且動作型態同向的分段合併判斷並一併反轉；`flip_by_asymmetry` 的聲音起點門檻在 `audio < 0` 時改為線性插值。`tests/test_chunks.py`、`tests/test_parts.py` 新增 3 個測試；PLAN、DEVELOPMENT 更新。
- 驗證：`uv run pytest` 297 passed；`validate --replay`（28 段）：預設 dev F1 0.723 → 0.747（原 13 段 0.784 → 0.805）、r 0.507 → 0.548，test F1 0.710 → 0.724、r 0.548 → 0.558；`--preset user` dev F1 0.732 → 0.739、r 0.518 → 0.529，test 0.735（12/12 逐點相同）；保留組 holdout 10 段預設 F1 0.655 → 0.661、r 0.407 → 0.429，`user` F1 0.645 → 0.652、r 0.396 → 0.420。

## 2026-11-05 — 授權條款、第三方聲明、免責與 Claude 開發說明（commit: `Add MIT license, third-party notices and compliance docs`）
- 目的：準備發布到 GitHub，補齊開源授權條款、第三方套件與模型來源致謝、免責與使用說明，以及使用 Claude 開發的說明，並將 git 作者信箱改為 GitHub noreply 信箱。
- 修改：新增 `LICENSE`（MIT）與 `THIRD_PARTY_NOTICES.md`；`pyproject.toml` 宣告授權檔；`README.md`、`README.en.md`、`packaging/windows/README.txt`、`packaging/windows/README.en.txt` 補上使用注意與免責聲明、參考來源與致謝、Claude 協作開發說明與授權條款；`packaging/windows/build.ps1`、`smoke-test.ps1` 與 `docker/Dockerfile` 加入授權檔案；DEVELOPMENT、PLAN 更新；git 信箱改為 `349598811+yumeyis@users.noreply.github.com`。
- 驗證：`uv run pytest` 通過；`uv build --wheel` 通過。只改文件與建置設定，沒有跑素材驗證。

## 2026-11-05 — 多語言：英文版與語言包（commit: `Add the English version and language packs`）
- 目的：使用者要求增加英文版本（UI、說明文件、Web UI、Windows 版），程式從資料夾中的 `lang` 讀取語言包檔案、在介面中選擇套用，並提供標準模板讓人翻譯成其他語言；預設跟系統語言，Web UI 切換即時生效。
- 修改：新增 `i18n.py` 與 `lang/`（`zh-TW.toml` 原稿、`en.toml`、`_template.toml`，420 個文字）、CLI 的 `--lang` 與 `lang list／template／check`；程式中的中文字串（`options.py`、`webui.py`、`pipeline.py`、`preview.py`、`devices.py`、`report.py` 等）改成 `t("key")`，Web UI「設定」分頁最上方加語言清單；新增 `README.en.md`、`docker/README.en.md`、`packaging/windows/README.en.txt`；Windows 版把 `lang\` 放在 exe 旁、啟動程式設 `FUNSCRIPT_GEN_LANG_DIR`；compose 檔加 `FUNSCRIPT_GEN_LANG`；CLAUDE.md、DEVELOPMENT、ARCHITECTURE、PLAN 更新。
- 驗證：`uv run pytest` 294 passed（新增 23 個語言包測試），testhost（Windows）288 passed；headless Chromium 確認切換語言立即生效並記住；Windows 版建置與冒煙測試通過、Docker 建置與啟動通過；`validate --replay` 28 段 × 2 組設定動作逐點相同。英文譯文未經母語者校對；Windows 桌面視窗中的切換未實際開啟驗證。

## 2026-11-05 — Windows 免安裝版與桌面模式（commit: `Add the Windows portable build and the desktop app`）
- 目的：使用者要求建置 Windows 免安裝版，有指令與圖形介面兩種用法，用 GitHub 的工具建置；圖形介面的輸出預設在 `data\out`，可設定存到影片旁邊。
- 修改：新增 `paths.py`（`FUNSCRIPT_GEN_HOME` 把所有寫入的檔案集中到一個資料夾）、`app.py` 與 `funscript-gen app`（本機的 Web UI，pywebview 視窗或瀏覽器，可直接用影片路徑與原生選檔對話框）；Web UI 新增本機路徑欄、「同時把腳本存到影片旁邊」（不覆寫非本程式產生的腳本）、「開啟輸出資料夾」；`pyproject.toml` 在 Windows 自動用 `onnxruntime-directml`，新增選配 `gui`；新增 `packaging/windows/`（`build.ps1`、C# 啟動程式、冒煙測試、zip 說明）與 `.github/workflows/windows.yml`（手動執行產生 artifact，推 `v*` 標籤建立草稿 Release）。README、DEVELOPMENT、ARCHITECTURE、PLAN、CLAUDE.md 4.1 更新。
- 驗證：`uv run pytest` 本機與 testhost（Windows）都全部通過；testhost 上建置出 858 MB 的資料夾（zip 312 MB），冒煙測試通過（CLI 產生腳本、視窗後端可載入、伺服器回應、使用者目錄沒有新增檔案），光流用 OpenCL、部位框用 DirectML。圖形介面的視窗沒有在桌面上實際開啟過；沒改分析與輸出邏輯，沒有跑素材驗證。

## 2026-11-05 — Docker 建置設定（commit: `Add Docker build and compose files`）
- 目的：使用者要求在 `docker/` 提供建置用的 Dockerfile、一般版與加上 Ollama 的 docker-compose，以及建置與使用說明。
- 修改：新增 `docker/`（`Dockerfile`、`entrypoint.sh`、`Dockerfile.dockerignore`、`docker-compose.yaml`、`docker-compose.ollama.yaml`、`README.md`）；`.gitignore` 加入容器的資料夾；README、DEVELOPMENT、PLAN 更新，CLAUDE.md 加上建置方式改變時要更新 `docker/` 的規則。
- 驗證：`uv run pytest` 通過；映像檔建置成功，容器內 CLI 產生腳本、Web UI 回應 200，Ollama 版以小模型確認啟動流程（GPU 上未實測）。只加建置設定，沒有跑素材驗證。

## 2026-11-04 — 運算裝置移到設定分頁（commit: `Move the compute settings to the settings tab`）
- 目的：使用者要求在「設定」分頁設定運算裝置，並讓「設定」分頁的各大項可以收合。
- 修改：`webui.py` 的「設定」分頁改成 AI API、運算裝置、輸出檔案三個可收合區塊；運算裝置從「產生」分頁移過來，點選後立即記住，「設定組」與「還原預設設定」不再改動它。README、PLAN 更新。
- 驗證：`uv run pytest` 通過；headless Chromium 確認版面、收合與立即記住。只改 Web UI，沒有跑素材驗證。

## 2026-11-04 — 運算裝置設定（Auto／GPU／CPU）與光流的 GPU 模式（commit: `Add Auto/GPU/CPU compute settings and OpenCL optical flow`）
- 目的：使用者要求檢查能用 GPU 的流程是否都有 GPU 模式，並新增整體與個別步驟的運算裝置設定（Auto／GPU／CPU，預設 Auto；選 GPU 但不可用時提醒並停止）。
- 修改：新增 `devices.py`；光流加 OpenCL 路徑（`tracking/flow.py`），部位框的 GPU 載入失敗時可以不退回 CPU（`tracking/parts.py`），骨架的裝置依設定；`options.py` 新增 `--compute`、`--flow-compute`、`--part-compute`、`--pose-compute`，Web UI 新增「運算裝置」區塊（分段控制項）；CLI、Web UI、批次在開始前檢查，結果列出實際用的裝置。硬體解碼量過後不採用。README、DEVELOPMENT、ARCHITECTURE、PLAN、CLAUDE.md 4.1 更新。
- 驗證：`uv run pytest` 通過；本機（沒有 GPU）25 段逐點相同；testhost 6 段 GPU 對 CPU 光流 F1 0.575 → 0.576，整批 390 → 292 秒。

## 2026-11-04 — 預覽分頁改為一起選取影片與 funscript（commit: `Pick the video and script together in the preview tab`）
- 目的：使用者要求取消從伺服器找同名檔案的功能，把一起選取改成預設行為，並保留原本分別上傳的方式。
- 修改：`webui.py` 移除「自動代入 Video & funscript」勾選框與找同名檔案的程式；影片欄一律可同時選影片與 funscript 並分到兩欄。README、PLAN 更新。
- 驗證：`uv run pytest` 通過；headless Chromium 實際上傳確認一起選取與分別上傳。只改 Web UI，沒有跑素材驗證。

## 2026-11-04 — 預覽分頁自動代入同名檔案（commit: `Auto-fill the same-name video or script in the preview tab`）
- 目的：使用者要求上傳影片或 funscript 時自動代入同名的另一個檔案。
- 修改：`webui.py` 的預覽分頁新增「自動代入 Video & funscript」選項：影片欄可同時選影片與 funscript 並分到兩欄；只選一個時從之前上傳過的檔案與產生的輸出中找同名檔案（瀏覽器不提供原本的資料夾）。README 補上用法。
- 驗證：`uv run pytest` 251 項通過；headless Chromium 實際上傳確認。只改 Web UI，沒有跑素材驗證。

## 2026-11-04 — 評估：鏡頭移動改用相似變換（commit: `Evaluate a similarity camera model for the flow`）
- 目的：目前扣掉的全畫面中位數只代表平移，扣不掉推拉鏡頭；外部意見提到鏡頭移動補償。
- 修改：新增 `scripts/camera_model.py`（離線比較鏡頭移動的估計方式）；試做的 `--camera-model` 選項驗證後已還原；PLAN.md 記錄數字與已放棄的方案。主程式不變。
- 驗證：`uv run pytest` 通過。dev＋test F1 0.718 → 0.708；G03／04／06 +0.024，但 holdout 的 G 系列沒有重現（F1u +0.002），不採用。

## 2026-11-04 — 評估：單目深度估計判斷方向（commit: `Evaluate monocular depth as a stroke direction cue`）
- 目的：使用者提供的外部意見建議用深度估計判斷兩人靠近或遠離；意見中只有這個方法還沒試過。
- 修改：新增 `scripts/depth_sign.py`（取鏡頭、在 GPU 主機跑 Depth Anything V2、離線評估）；`scripts/depth_compare.py` 的 `load_scenes` 可以依素材調整 render 設定；PLAN.md、DEVELOPMENT.md 記錄數字與已放棄的方案。主程式不變。
- 驗證：`uv run pytest` 248 通過。2D 上有害（test F1 0.710 → 0.620）；G 系列 holdout 0.655 → 0.662，但和降低快慢門檻的效果重疊（疊上去 0.669 → 0.670），不採用。

## 2026-11-04 — 確認手／口比較不影響其他影片（commit: `Confirm the hand-or-mouth pick leaves other clips unchanged`）
- 目的：使用者詢問這個功能是否影響其他類型的影片
- 修改：只更新 PLAN.md 的開發紀錄，未改程式
- 驗證：38 段中只有 3 個鏡頭觸發，差異都在該鏡頭內；6 段抽查在 `default`、`user-general` 與修改前逐點相同

## 2026-11-04 — 評估：以身體部位組成的物件距離判斷方向（commit: `Evaluate the distance between people found from their body parts`）
- 目的：使用者提議，看不到陰莖＋陰道時，以身體部位組成男女（或不明）物件，物件靠近＝向下，每個鏡頭取一個來回判斷。
- 修改：新增 `scripts/body_sign.py`（選出鏡頭、以 imgutils 偵測頭與身體部位、離線評估）；PLAN.md 記錄數字與已放棄的方案。主程式不變。
- 驗證：dev＋test 210 個鏡頭，和人工腳本同向 46–58%（隨機水準），所有變體 dev 平均 F1 下降（0.723 → 0.566–0.712；只用在 G 系列 0.712–0.724）。`uv run pytest` 248 個通過。

## 2026-11-04 — 手和口：第二名的機率設下限（commit: `Compare the hand and the mouth only when both are likely`）
- 目的：使用者要求；前兩名是手和口的鏡頭大多第二名的機率不到 0.01，AI 其實確定只有一個部位。
- 修改：`options.py` 新增 `--contact-min-prob`（分析階段，預設 0.1；0 等於之前的做法）；`pipeline.py` 的 `_pick_contacts` 在第二名低於下限時不框、不比較；`validation.toml` 新增設定組 `user-cmp05`、`user-cmp0`、`user-noct`；測試與文件。
- 驗證：同一台機器上和關閉比較，0／0.05／0.1 的 dev 平均 F1 差都在 ±0.0002；0.1 時 dev＋test 只有 2 個鏡頭比較移動量（G06 一個鏡頭 r 0.65 → 0.95），holdout 只有 G05 一個、分數不變。`uv run pytest` 248 個通過。

## 2026-11-04 — 手和口的區域加上陰莖（commit: `Join the penis box to the chosen hand or mouth box`）
- 目的：使用者要求，只用手或口的框時少了陰莖，A01 的兩個鏡頭因此變差。
- 修改：`ai/prompts.py` 的 `ContactBoxes` 加上陰莖的框；`pipeline.py` 的 `_pick_contact_region` 以選中的框與陰莖框的聯集當生殖器區域（移動量仍只比手和口）；PLAN.md 更正上一版的 G04、G02 數字（testhost 的光流差異與 AI 快取被覆蓋，不是這個功能）。
- 驗證：`--preset user` dev 16 段 F1 0.732 → 0.732、test 不變、holdout 0.645 → 0.644；A01 −0.032 → −0.002，G06 81.5 s r 0.65 → 0.95 保留。`uv run pytest` 247 個通過。

## 2026-11-04 — Hybrid：手和口都可能時跟著移動較大的（commit: `Follow the hand or the mouth, whichever moves more`）
- 目的：使用者要求，接觸部位機率前兩名是手和口時，優先用移動較大的那個判斷。
- 修改：`ai/openai_compat.py` 新增 `choice_probs`（接續快取的回答、只產生 1 個 token，以 token 機率算出每個選項的機率；Ollama 不支援）；`ai/prompts.py` 新增手和口的框（`ContactBoxes`）；`pipeline.py` 的 `_pick_contacts` 與 `_pick_contact_region`（兩個框中位移範圍較大的成為生殖器區域）；`options.py` 新增 `--contact-pick`（分析階段，預設開）；測試與文件。
- 驗證：`--preset user` dev 16 段 F1 0.732 → 0.727、r 0.518 → 0.520，test 不變，holdout F1 0.646 → 0.644；G06 一個鏡頭 r 0.65 → 0.95，A01 兩個鏡頭變差。`uv run pytest` 247 個通過。

## 2026-11-04 — 評估：部位框、快慢、聲音的每種組合（commit: `Evaluate every subset of the part, asymmetry and sound checks`）
- 目的：使用者提問，三種方向判斷單獨、兩兩、三種一起，哪個最好，要不要用信心投票。
- 修改：`scripts/sign_vote.py` 新增 `--subsets`（每種組合的規則與投票，門檻用預設或每次留一個系列依正確率或 F1 選），每段分數依翻轉的鏡頭快取；PLAN.md 記錄比較表與門檻的發現。主程式不變。
- 驗證：三種一起的現行規則最好（dev 0.723、test 0.710、holdout 0.655），每種組合的投票都不比規則好；聲音單獨使用比不判斷差。快慢的最佳門檻 2D 是 0.5、3D 是 0.2，只對 G 用 0.2 時 dev 0.742、holdout 0.669（假設 3D 已知）。`uv run pytest` 241 個通過。

## 2026-11-04 — 評估：WD 深淺模型與原有方向判斷的組合（commit: `Evaluate combining the WD depth model with the direction checks`）
- 目的：使用者提問，只用 WD 深淺模型和原有方式（部位框、快慢、聲音）依信心投票能否改進分數。
- 修改：`scripts/sign_vote.py` 新增 `addon_report`（保留現行規則、只在沒有證據的組加翻，以及只在 G 系列的模擬）；PLAN.md 記錄數字與解讀。主程式不變。
- 驗證：24 組投票設定沒有一組在 dev 與 test 都不低於現行規則；「WD 與快慢同向才翻」dev 0.723 → 0.729、test 0.710 不變、holdout 0.655 → 0.664，增益只有 1–2 個鏡頭，不採用。`uv run pytest` 241 個通過。

## 2026-11-04 — 評估：現行方向錯的鏡頭中各線索的正確率（commit: `Report the direction cues on the scenes the output gets wrong`）
- 目的：使用者提問，哪個試過的方式在現行輸出方向錯的鏡頭上正確率高。
- 修改：`scripts/sign_vote.py` 新增 `wrong_report`（以現行輸出為準，錯的組與對的組中各線索主張翻轉的比例，G 系列分開）；PLAN.md 記錄數字，並在後續工作加上「3D 素材降低快慢門檻」（未驗證）。主程式不變。
- 驗證：G 系列的快慢 ≥ 0.2 在錯的組中對 11/12、只改錯 1/23（holdout 10/11、0/35），其他系列改錯多於改對；WD ≥ 0.4 對 16/21 但改錯 11/64。`uv run pytest` 241 個通過。

## 2026-11-04 — 評估：所有方向線索的信心加權投票（commit: `Evaluate confidence-weighted votes over the direction cues`）
- 目的：使用者提問，把試過的方向判斷都做、依信心分配權重投票，能否比現行規則好。
- 修改：新增 `scripts/sign_vote.py`（7 種線索的逐組比較、三種信心校準的投票與堆疊，每次留一個系列擬合、以實際 F1 評分）；PLAN.md 記錄完整數字、原因與已放棄的方案，DEVELOPMENT.md 加一條已知問題。主程式不變。
- 驗證：約 100 組設定中沒有一組在 dev 與 test 都不低於現行規則（dev 0.723、test 0.710）；dev 最好 0.733 時 test 0.630–0.678，不採用。`uv run pytest` 241 個通過。

## 2026-11-04 — 最小間隔 60 ms，檢查限速（commit: `Keep turning points of strokes above 5.5 Hz`）
- 目的：D03 約 5 Hz 的行程有一半被刪掉；使用者另外要求檢查限速 500 單位／秒對 OSR2 是否合適。
- 修改：`signal/process.py` 的 `min_interval_ms` 90 → 60（加測試 `test_fast_strokes_keep_their_turning_points`）；限速維持 500，README 註明伺服馬達較好的 OSR2 可調到 600。另外試了「沒有節奏時高通後再找節奏」，dev／test 都下降，沒有採用。PLAN、DEVELOPMENT 更新。
- 驗證：`--replay` 38 段 default F1 0.700 → 0.701、user 0.707 → 0.710，沒有一段下降超過 0.007（D03 user +0.075）；holdout 不變。限速 600–1000 的分數差 ≤ 0.001。`uv run pytest` 241 個通過。

## 2026-11-04 — 評估：以人工腳本訓練深淺比較器（commit: `Evaluate a depth model trained on the hand-made scripts`）
- 目的：使用者選擇試「用人工腳本訓練哪一幀比較深」，看能否同時改善方向與每一下的大小。
- 修改：新增 `scripts/depth_compare.py`（取鏡頭、在 GPU 主機抽 DINOv2／CLIP／WD 標籤模型的特徵、留一個系列的嶺迴歸與翻轉模擬）；PLAN.md 記錄完整數字與已放棄的方案，DEVELOPMENT.md 加一條已知問題。主程式不變。
- 驗證：預測和人工腳本相關只有 0.2–0.45；只翻信心高的鏡頭時 dev F1 0.720 → 0.744（主要是 B02 的一個鏡頭），test 0.710 → 0.714、holdout 0.655 → 0.660，不採用。`uv run pytest` 240 個通過。

## 2026-11-04 — 評估 OpenFunML（commit: `Evaluate OpenFunML as a pipeline cue or plugin`）
- 目的：使用者要求評估 OpenFunML（ONNX 模型＋後處理）能否融入流程或做成可選外掛。
- 修改：PLAN.md 記錄模型規格、授權、完整數字與決定（含已放棄的方案一行），DEVELOPMENT.md 加上比較摘要。評估腳本移植了它沒有授權的後處理，留在 scratchpad 不提交；主程式不變。
- 驗證：38 段 F1 本專案預設 0.700、OpenFunML 0.2 0.639、0.3 0.602；當方向證據時，和本專案相反的鏡頭中只對 36/108，不採用。`uv run pytest` 240 個通過。

## 2026-11-04 — 評估：以遮擋判斷方向（commit: `Evaluate occlusion at the contact point as a direction cue`）
- 目的：使用者要求研究提高行程方向精確度的方法；先試成本最低的「插入時像素消失、拔出時重新出現」。
- 修改：新增 `scripts/occlusion_sign.py`（光流正反向一致性的遮擋圖與離線評估）；PLAN.md 記錄數字、已放棄的方案與其他候選。主程式不變。
- 驗證：dev 輸出錯的 49 個鏡頭中線索只對 47%（隨機水準），改對 17、改錯 29，不採用；`uv run pytest` 240 個通過。

## 2026-11-04 — 和 Funscript-Flow 比較分數（commit: `Compare scores with Funscript-Flow`）
- 目的：使用者要求在隔離環境中測試 Funscript-Flow 的分數，並和本專案比較。
- 修改：新增 `scripts/score_external.py`（用驗證的評分方式評分其他工具的輸出，`compare-runs` 可直接並列）；PLAN.md 記錄隔離方式與完整數字，DEVELOPMENT.md 加上比較摘要。主程式不變。
- 驗證：Funscript-Flow 在斷網、唯讀的 Docker 容器中跑全部 38 段：dev F1 0.492 對本專案 0.720、test 0.580 對 0.710、holdout 0.499 對 0.655；每個鏡頭方向都換成對的（F1u）也是本專案較高。

## 2026-11-04 — 評估：沒有方向證據的鏡頭預設顛倒（commit: `Evaluate inverting the default sign of scenes without evidence`）
- 目的：使用者提議把無法判斷方向的鏡頭預設顛倒。
- 修改：只更新 PLAN.md（評估紀錄與已放棄的方案），程式不變。
- 驗證：離線統計存下的分析，維持預設方向的鏡頭中對的多於錯的（dev 1257 對 371 秒、test 404 對 52 秒），G 系列與短鏡頭接近一半一半，所以不採用；`uv run pytest` 240 個通過。

## 2026-11-03 — 拖曳位置條設定選取點的位置（commit: `Set the selected action's position by dragging the position bar`）
- 目的：使用者要求編輯時能拖動右邊的位置條設定選取點的位置。
- 修改：`preview.py` 編輯模式下在位置條上按住拖曳設定選取點的位置（多個點一起移動），按下時跳到該點；說明文字、README、PLAN 同步。
- 驗證：`uv run pytest` 240 個通過；headless Chromium 確認單點、多點（受 0–100 限制）、一次復原，未編輯時不受影響。只改播放器，不影響輸出。

## 2026-11-03 — 幅度與頂點／底點只改選取的點（commit: `Apply amplitude and tops or bottoms to the selected actions`）
- 目的：使用者同意讓幅度與頂點／底點在選取多個點時只改這些點。
- 修改：`preview.py` 新增 `target()`（選取兩個以上的點時是這些點，否則是目前鏡頭），`scaleScene`、`levelScene` 改用它，`setTurns` 改為接受索引清單；說明文字、README、`tests/test_preview.py`、PLAN 同步。
- 驗證：`uv run pytest` 240 個通過；headless Chromium 確認只改選取的點、`-` 還原、只選一個點時仍是整個鏡頭。只改播放器，不影響輸出。

## 2026-11-03 — 時間軸框選多個點、右鍵拖曳捲動（commit: `Box-select actions and pan the timeline with the right button`）
- 目的：使用者要求在時間軸上用左鍵拖曳選取多個點來操作、右鍵拖曳移動時間軸。
- 修改：`preview.py` 的選取改成點的集合，編輯時空白處左鍵拖曳框選（`Shift` 加選），選取的點一起拖曳（不越過未選取的點）、`↑` `↓` 與刪除；右鍵拖曳捲動時間軸；README 的說明與按鍵表、`tests/test_preview.py`、PLAN 同步。
- 驗證：`uv run pytest` 240 個通過；headless Chromium 模擬滑鼠確認框選、整組拖曳與限制、刪除、復原、右鍵捲動。只改播放器，不影響輸出。

## 2026-11-03 — 播放器跳到上一個／下一個鏡頭（commit: `Jump to the previous or next scene in the player`）
- 目的：使用者要求能快速跳到上一個或下一個鏡頭。
- 修改：`preview.py` 的資訊列新增「上一個鏡頭」「下一個鏡頭」按鈕與 `PageUp`／`PageDown`（`jumpScene`，沒有切點時隱藏）；README 的按鍵表、`tests/test_preview.py`、PLAN 同步。
- 驗證：`uv run pytest` 239 個通過；headless Chromium 確認按鍵與按鈕跳到正確的鏡頭開頭、在第一個與最後一個鏡頭停住。只改播放器，不影響輸出。

## 2026-11-03 — 把鏡頭的頂點或底點設成指定位置（commit: `Set a scene's tops or bottoms to a position in the player`）
- 目的：使用者要求整段鏡頭的波峰或波谷能一次設成某個位置。
- 修改：`preview.py` 的資訊列新增「頂點」「底點」輸入與「設定」按鈕，`turns` 找出每個波峰／波谷的動作點（停頓算一個），`setTurns` 改這些點、中間的點依比例跟著移動；`webui.py` 的說明、README、`tests/test_preview.py`、PLAN 同步。
- 驗證：`uv run pytest` 239 個通過；headless Chromium 確認按鈕、`Enter` 與復原，只改目前鏡頭。只改播放器，不影響輸出。

## 2026-11-03 — 鏡頭幅度依每一下各自的中點縮放（commit: `Scale each stroke around its own middle in the player`）
- 目的：預覽播放器的 `+`／`-` 原本以整個鏡頭的中點縮放，鏡頭內忽高忽低的動作會被推到頂端或底端截掉。
- 修改：`preview.py` 新增 `strokeCenters`，每個點以前後兩下行程中點的平均為準縮放（停頓保持平的）；README 的說明、`tests/test_preview.py` 新增測試；PLAN 同步。
- 驗證：`uv run pytest` 238 個通過；headless Chromium 確認 `+` 後 20–50／60–90 兩群各自放大、`-` 精確還原。只改播放器，不影響輸出。

## 2026-11-03 — 撤銷 AI 區分男女（commit: `Revert "Tell the sexes apart and track the largest man and woman"`）
- 目的：使用者提議以女物件與作用物件的距離決定行程方向（靠近＝向下），指示無效就撤銷區分男女的修改。
- 修改：`git revert 230decf`，程式、測試、README、DEVELOPMENT、ARCHITECTURE 回到修改前；PLAN 記錄兩次的結果與已放棄的方案，CHANGELOG 保留上一條。
- 驗證：離線評估（28 段的光流場＋AI 性別框）：依這個規則翻轉時改對與改錯的數量相近（門檻 0.2 改對 29、改錯 21），平均 F1 0.697 → 0.687，所有門檻都下降；`uv run pytest` 237 個通過，撤銷後抽查 5 段（B02、A06、H01、K01、C01，兩組設定）的輸出與 `flowit2` 逐點相同。

## 2026-11-03 — AI 區分男女，多於兩人時追蹤最大的男性與女性（commit: `Tell the sexes apart and track the largest man and woman`）
- 目的：使用者要求辨識男女；畫面中多於兩人時追蹤占畫面最大的人，而不是由 AI 自己挑。
- 修改：`ai/prompts.py` 的場景分析改為列出每個人（最多 6 人）的性別與框，Hybrid 的提示詞在多個陰莖時取最大的男性；`pipeline.py` 新增 `pick_pair`（最大的男性與女性，沒有一男一女時是最大的兩人），候選區域與分析區域都用它，AI 的互動區域大半不在這兩人身上時改用兩人的範圍；`ai-check` 標出追蹤的兩人與性別；新增 3 個測試；README、DEVELOPMENT、ARCHITECTURE、PLAN 同步。
- 驗證：`uv run pytest` 240 個通過；38 段素材都沒有多於兩人的鏡頭（新規則未觸發、未驗證）。AI 回答因提示詞改變而偏移：dev+test 28 段 `F1u` 0.753 → 0.755，F1 0.715 → 0.697（主要是 B02 整段方向翻反）；holdout F1 0.655 → 0.640、`F1u` 0.682 → 0.677。

## 2026-11-03 — Farneback 光流迭代 3 → 2 次（commit: `Run two Farneback iterations per pyramid level`）
- 目的：加快光流（分析時間的大部分）。
- 修改：`tracking/flow.py` 的 Farneback 參數改成常數 `FARNEBACK`、迭代 3 → 2 次，`scripts/flow_dump.py` 改用同一個常數；DEVELOPMENT 的驗證表、PLAN 同步。
- 驗證：`uv run pytest` 237 個通過；光流每幀快約 25%，整個流程快 9–13%（B03 42.1 → 36.8 秒）；dev+test 28 段 F1 0.713 → 0.715、`F1u` 持平；holdout F1 0.651 → 0.655。

## 2026-11-03 — 節奏濾波過的訊號改用 0.2 秒平滑（commit: `Smooth band-passed signals over 0.2 s`）
- 目的：重新檢查參數時，加寬平滑在不看方向的分數上有改善，但會抹掉沒有節奏濾波的鏡頭中很快的小行程（D03）。
- 修改：`signal/process.py` 新增 `SignalParams.rhythm_smooth_window_s`（0.2 秒），只用在節奏濾波過的段落，其他維持 0.15 秒；新增 1 個測試；DEVELOPMENT 的驗證表、ARCHITECTURE、PLAN 同步。
- 驗證：`uv run pytest` 237 個通過；dev+test 28 段 F1 0.707 → 0.713、`F1u` 0.743 → 0.753、r 0.507 → 0.521；holdout F1 0.655 → 0.651（`F1u` 持平）、r 0.398 → 0.409。

## 2026-11-03 — 驗證加入不看方向的分數、依實際幀率計算（commit: `Add direction-free scores and use the measured frame rate`）
- 目的：重新檢查參數時，`region_pick_margin` 0 → 0.1 讓 28 段平均 F1 +0.012，結果只是 2–3 個鏡頭碰巧翻了方向，平均 F1 分不出真的改善與方向的雜訊；另外去漂移視窗與快慢判斷以 `--fps`（30）當每秒幀數，24 fps 的影片會算錯。
- 修改：`validate.py` 新增 `upright()` 與 `F1u`／`ru` 兩欄（負相關的鏡頭上下顛倒後評分）；`tracking/flow.py` 新增 `sample_rate()`，`integrate`、`FlowTracker.signal`、快慢判斷與骨架訊號改用實際幀率；新增 3 個測試；CLAUDE.md、DEVELOPMENT、PLAN 同步。
- 驗證：`uv run pytest` 236 個通過、2 個略過；dev+test 28 段 `--replay` 與 8 段 29.97 fps 素材的完整執行都和修改前逐點相同。新基準 `F1u`／`ru`：預設 dev 16 段 0.760／0.600、test 0.722／0.576。

## 2026-11-03 — 直式影片不放大算光流（commit: `Compute flow on portrait frames without enlarging them`）
- 目的：直式影片解碼成 360×640 後被放大到 480×853 才算光流，像素多 1.8 倍卻沒有多出細節，是直式影片分析慢的主因。
- 修改：`tracking/flow.py` 的 `FlowTracker.update` 在畫面比 `--flow-width` 窄時直接算，再換算回 480 寬的單位與格子；新增 `test_narrow_frames_are_not_enlarged`；`--flow-width` 的說明、README、DEVELOPMENT、ARCHITECTURE、PLAN 同步。
- 驗證：`uv run pytest` 233 個通過；直式素材快約 35–38%（B03 67.6 → 41.6 秒）；只有 7 段直式素材輸出改變，dev 16 段 F1 0.720 → 0.718、test 0.689 → 0.691（雜訊範圍）。

## 2026-11-03 — 收斂 PLAN.md、歸檔開發紀錄（commit: `Condense PLAN.md and archive the old dev log`）
- 目的：PLAN.md 830 行、110 條紀錄全部打勾，看不出目前要做什麼與哪些決策仍有效。
- 修改：依時間的完整紀錄與舊驗證表移到 `docs/archive/PLAN-archive.md`（刪掉已不存在的實驗腳本與過時的待辦）；PLAN 改為架構、待解決的問題、仍有效的決策與限制、已放棄的方案（每項一行）、後續工作與最近的紀錄；漏掉的素材名稱改用代號 O01；CLAUDE.md、DEVELOPMENT、ARCHITECTURE、CHANGELOG 與兩個腳本註解的連結改指到新位置。
- 驗證：只改文件，沒有重跑驗證素材；`uv run pytest` 232 個通過、2 個略過。

## 2026-11-03 — 公開前去識別化（commit: `Use aliases for clip and host names in committed files`）
- 目的：專案會公開，提交的檔案不寫素材的實際檔名、來源與測試主機名稱。
- 修改：文件、`validation.toml`、程式與測試的註解改用素材代號（`A01`…`N01`）與 `testhost`；以主機命名的驗證腳本改名為 `scripts/remote_validate.ps1`；對照寫在不提交的 `deidentify.local.toml`，`validate` 依它找到實際檔案；新增 `tests/test_private_names.py` 檢查會提交的檔案沒有實際名稱；CLAUDE.md 新增規則、同步指令附上對照檔。
- 驗證：`uv run pytest` 232 個通過、2 個略過；dev+test 28 段 `--replay` 和修改前逐點相同。git 歷史仍有實際名稱，未處理。

## 2026-11-03 — 光流與部位框切成小段平行計算（commit: `Compute optical flow and part boxes in parallel pieces`）
- 目的：加快處理速度（使用者選擇）。量測後解碼只佔幾秒、光流佔大部分，而每個鏡頭只用一個核心，只有一兩個鏡頭的影片大部分核心閒置。
- 修改：`pipeline._analyze` 把每個鏡頭切成最多 5 秒的小段平行計算光流，`FlowTracker.extend` 補上接縫的一幀後接回；部位框偵測也切成小段（`parts.cached_detect_span` 的 `pool`）；修正 `iter_frames` 從關鍵幀開始解碼時多留一幀的問題（關鍵幀和前一幀落在同一個時間格時）；`--flow-workers` 改為同時計算的小段數；README、DEVELOPMENT、ARCHITECTURE、PLAN、測試。DIS 光流快 5.6 倍但 dev F1 0.720 → 0.615，不採用。
- 驗證：`uv run pytest` 230 個通過、2 個略過；dev、test、holdout 38 段和修改前的程式逐點相同。不含部位框時 K01 35.8 → 16.8 秒、B03 79.9 → 65.8 秒；部位框在 CPU 上沒有快取時是瓶頸，多鏡頭的影片幾乎不變。

## 2026-11-03 — Ollama 原生後端（commit: `Add an Ollama native API backend`）
- 目的：使用者選擇「其他 AI 後端」。實測發現 Ollama 的 `/v1` 不能用：預設上下文 4096 會拒絕 4 張圖（每張約 1040 token），也不保留標籤與圖片的順序。
- 修改：新增 `ai/ollama.py`（`/api/chat`、`num_ctx`、`[img]` 標記位置）；`openai_compat.py` 的重試與快取改為共用；`config.py` 新增 `VLLM_BACKEND`、`VLLM_NUM_CTX`（16384），Ollama 的逾時乘上同時請求數；Web UI「設定」分頁、`set-env.sh`、`.env.example`、metadata 的 `ai_backend`；README、DEVELOPMENT、ARCHITECTURE、PLAN、CLAUDE.md、測試。
- 驗證：`uv run pytest` 225 個通過、2 個略過；vLLM 後端 25 段逐點相同。testhost 的 Ollama 4B 跑 3 段 89 個鏡頭 AI 全部成功（A04 F1 0.776 → 0.682，差異來自模型）；8B 在 RTX 3070 上放不下，未驗證。

## 2026-11-02 — 批次產生（commit: `Add batch generation to the CLI and web UI`）
- 目的：有很多影片時不必一支一支處理（使用者選擇「易用性」）。
- 修改：新增 `batch.py`（找影片、輸出檔名、依序產生，失敗時繼續）；CLI 新增 `batch`（資料夾、`-r`、`-o`、預設略過已有腳本的影片）；Web UI 新增「批次」分頁（多支影片、結果表、取消、在「產生」分頁開啟結果以反轉或編輯）；README、DEVELOPMENT、ARCHITECTURE、PLAN、測試。
- 驗證：`uv run pytest` 220 個通過、2 個略過；無頭 Chromium 中操作「批次」分頁與開啟結果、CLI 對合成影片跑兩次（第二次全部略過）。輸出邏輯沒有改，沒有重跑素材驗證。

## 2026-11-02 — 評估快速行程的時間誤差（commit: `Evaluate the timing of fast-stroke turning points`）
- 目的：使用者選擇的下一步：之前的診斷顯示快速行程的轉折點常有時間偏移，想確認偏移出在光流還是後處理，以及能不能修正。
- 修改：新增診斷腳本 `scripts/turn_timing.py`（各處理階段的時間差、失分所在的鏡頭、用人工腳本挑的平移上限、用聲音預測平移）；PLAN、DEVELOPMENT。主程式沒有改變。
- 驗證：`uv run pytest` 211 個通過、2 個略過。方向對的鏡頭中轉折點和人工腳本中位差約一幀（33 ms），150 ms 內命中 dev 0.88、test 0.83；剩下的偏移各鏡頭方向不一，用聲音修正 dev F1 0.721 → 0.727、test 0.693 → 0.691，不採用。

## 2026-11-02 — 「預覽」分頁的鏡頭識別（commit: `List and re-split scenes in the preview tab`）
- 目的：載入別處做的腳本時，看得到切出的鏡頭，並能調整切分，以便逐鏡頭反轉與檢查。
- 修改：`video/scenes.py` 新增 `frame_diffs`、`split_scenes`、`cut_strength`（`detect_scenes` 改用共用的切分判斷）；「預覽」分頁新增自己的靈敏度、「重新切分鏡頭」（不必重新解碼）、鏡頭數摘要與鏡頭表（切換強度、點擊反轉）；README、PLAN、測試。
- 驗證：`uv run pytest` 211 個通過、2 個略過；38 段素材修改前後的鏡頭切分（含關鍵幀）完全相同，輸出不變。

## 2026-11-02 — 預覽的播放速度、編輯說明與鏡頭幅度（commit: `Add playback speed, edit key help and scene amplitude to the preview`）
- 目的：手動修正更順：修掉編輯後在鏡頭表點「反轉」會丟掉未儲存編輯的 bug，並依使用者要求加上放慢／加快播放、編輯按鍵的說明、依鏡頭放大或縮小行程。
- 修改：`preview.py` 播放器新增 `[` `]` 播放速度（0.25–2 倍，記住上次的設定）、編輯時顯示的按鍵一覽、`A`／`Insert` 在播放位置新增動作點、`-` `+` 以鏡頭中點為準縮放目前鏡頭的位置（可復原、要儲存）；`webui.py` 的鏡頭表點擊改為先讀播放器的編輯與播放位置；README、PLAN、測試。
- 驗證：`uv run pytest` 208 個通過、2 個略過；無頭 Chromium 中模擬按鍵確認速度、縮放（截斷後可還原）、新增、刪除與復原。只改預覽，沒有重跑素材驗證。

## 2026-11-02 — 評估以音源分離改善聲音的方向線索（commit: `Evaluate Demucs stems for the sound direction cue`）
- 目的：使用者選擇的第 3 項 AI 元件：配樂與人聲會蓋過撞擊聲，分離後聲音的方向線索可能更準，而且不需要部位框。
- 修改：新增實驗腳本 `scripts/audio_stems.py`（在 GPU 主機上用 Demucs 分離各段聲音、算各音軌的起點包絡線，再和人工腳本比較並重新 render）；PLAN、DEVELOPMENT。主程式沒有改變。
- 驗證：`uv run pytest` 206 個通過、2 個略過。去掉人聲後 dev 的聲音判斷正確率 74% → 81%，test 75% → 67%；整段分數換成鼓的音軌時 dev r 0.473 → 0.482、test 不變，在雜訊範圍內，不採用。

## 2026-11-02 — 評估 SAM2 遮罩與 Hybrid 改用部位框（commit: `Evaluate SAM2 penis masks and part-box hybrid focus`）
- 目的：使用者選擇試新的 AI 元件：(1) 用 SAM2 逐幀分割陰莖，量行程的方向與深淺；(2) Hybrid 的生殖器區域改由部位框決定。
- 修改：新增實驗腳本 `scripts/mask_depth.py`（從存下的分析產生提示框、在 GPU 主機上跑 SAM2、和人工腳本比較）；`scripts/remote_validate.ps1` 新增 `-Run`，實驗腳本也受 CPU 上限；PLAN、DEVELOPMENT、CLAUDE.md。第 2 項的程式（`--part-focus`）試完已還原，主程式沒有改變。
- 驗證：`uv run pytest` 206 個通過、2 個略過。SAM2 遮罩和人工腳本的相關中位數 0.78（部位框 0.57–0.67），但換成位置後 dev r 0.473 → 0.402–0.478，沒有一種做法在 dev 上變好；部位框決定區域讓 Hybrid dev F1 0.720 → 0.701，只換逐幀選擇幾乎不變。兩者都不採用。

## 2026-11-02 — README 只給一般使用者（commit: `Split developer docs out of the README`）
- 目的：README 是給一般使用者看的，原本混了驗證分數、素材名稱、開發指令與專案結構。
- 修改：新增 `DEVELOPMENT.md`（驗證、基準表、已知問題的技術細節、專案結構）；README 改寫成使用者的用語，準確度只留一句概述；CLAUDE.md 的文件更新規則改為分別維護兩份；PLAN、ARCHITECTURE 更新連結。
- 驗證：只改文件；`uv run pytest` 206 個通過、2 個略過。

## 2026-11-02 — 高頻縮小幅度的預設改為 2 → 3 Hz（commit: `Start shrinking fast strokes at 2 Hz`）
- 目的：使用者要求檢查預設值。人工腳本到 2.5 Hz 都是滿行程，舊預設從 1.5 Hz 就開始縮，常見的 1.9 Hz 行程被縮成約 62%。
- 修改：`signal/process.py` 的 `SignalParams`、`options.py` 的 `freq_limit`／`freq_max` 預設由 1.5／2.0 改為 2.0／3.0（即 `user` 設定組的值）；新增 1 個測試；README、PLAN、ARCHITECTURE。
- 驗證：`uv run pytest` 206 個通過、2 個略過；`--replay` 預設設定 dev 16 段 r 0.467 → 0.485、test 0.521 → 0.529、holdout 0.386 → 0.398，F1 不變；`--preset user` 逐點相同。

## 2026-11-02 — 鏡頭切換處銜接（commit: `Bridge scene cuts with the previous stroke`）
- 目的：使用者回報切換處動作生硬：每個鏡頭各自找轉折點，切換處常留下放得下不只一下的空檔，或兩邊都停在高點（等於停住）。
- 修改：`signal/process.py` 新增 `bridge_gap`，`pipeline.finalize` 在反轉後於接不上節奏的切換處複製一次前一個鏡頭的最後一個行程（最多 2 點）；`--bridge`（預設開，Web UI「輸出」）；新增 6 個測試；README、PLAN、ARCHITECTURE。
- 驗證：`uv run pytest` 205 個通過、2 個略過；`--replay` 38 段，dev F1 0.717 → 0.719、test 0.688 → 0.690（user 0.724 → 0.726、0.708 → 0.709），holdout 的 N01 F1 −0.017。

## 2026-11-02 — 修正預覽播放器全黑（commit: `Keep the region overlay transparent over the video`）
- 目的：使用者回報播放器全黑、無法使用：分析區域的疊加層有不透明底色，蓋住了影片（`ef84a1a` 引入）。
- 修改：`preview.py` 的疊加層改成透明背景；新增回歸測試。
- 驗證：`uv run pytest` 199 個通過、2 個略過；淺色與深色主題下截圖確認影片可見、框的位置正確。

## 2026-11-02 — 預覽中直接編輯動作點（commit: `Edit actions in the preview player`）
- 目的：自動結果有少數錯誤時，不必換到 OpenFunscripter 就能直接修正個別動作點。
- 修改：`preview.py` 的播放器加編輯模式（拖曳、雙擊新增、刪除、方向鍵微調、復原）；`webui.py` 加「儲存編輯」按鈕，反轉時保留編輯，輸出檔標記 `hand_edited`；新增 4 個測試；README、PLAN。
- 驗證：`uv run pytest` 199 個通過、2 個略過；瀏覽器中模擬拖曳、新增、刪除、復原都正確。網頁上按「儲存編輯」的完整流程未實際操作。不影響產生的輸出。

## 2026-11-02 — 預覽疊加分析區域（commit: `Draw each scene's analysis region in the preview`）
- 目的：手動檢查輸出時，看得到每個鏡頭分析的是畫面哪裡，才能判斷動作和畫面對不上的原因。
- 修改：`preview.py` 新增 `scene_regions`，播放器在影片上畫出目前鏡頭的分析區域（混合模式標出當下用的是哪一個，`R` 切換顯示）；`webui.py` 在「產生」分頁的預覽傳入區域；新增 2 個測試；README、PLAN。
- 驗證：`uv run pytest` 196 個通過、2 個略過；用合成影片在瀏覽器截圖確認框的位置與混合模式的切換。不影響輸出。

## 2026-11-02 — 評估輸出漏掉的行程（commit: `Record where the missed strokes are lost`）
- 目的：輸出漏掉的行程是剩下最明確的 F1 失分，找出它們在哪一步不見、能不能用門檻救回。
- 修改：新增離線腳本 `scripts/lost_strokes.py`；主程式未改；PLAN。
- 驗證：dev 漏掉的行程 44% 在訊號中根本沒有、24% 只是行程旁的小起伏，被門檻去掉的只佔人工轉折點約 1.3%；`--min-prominence` 降到 0.05 dev F1 不變，不採用。

## 2026-11-02 — 評估人工腳本停住的地方（commit: `Record the hold evaluation`）
- 目的：上一項診斷中，人工腳本停住附近的轉折點命中率最低，評估 `--dwell` 能不能改善。
- 修改：只更新 PLAN（開發紀錄、待解決問題第 5 項）；主程式未改。
- 驗證：真正的停頓只佔人工轉折點約 1%（上一項的大多是慢而圓的峰谷）；`--dwell` 的參數最多把命中率從 0.25 提到 0.30，F1 反而下降，不採用。

## 2026-11-02 — 診斷漏掉的轉折點（commit: `Add a diagnosis of the missed turning points`）
- 目的：依使用者的評分優先順序（動作與頻率優先），找出 F1 失分的類型。
- 修改：新增離線腳本 `scripts/missed_points.py`（把沒配到的人工轉折點分成細小抖動、沒有輸出、峰谷顛倒、時間偏移、輸出較慢）；主程式未改；PLAN。
- 驗證：dev 沒配到的人工轉折點以細小抖動（0.27）、峰谷顛倒（0.09）、時間偏移（0.09）為主；人工腳本停住 0.5 秒以上的轉折點命中率只有 0.33。`uv run pytest` 194 個通過、2 個略過。

## 2026-11-02 — 評估 G 系列的部位框（commit: `Record the part detector test on the 3D clips`）
- 目的：G 系列（3D 動畫）的方向接近隨機，評估換用別的部位偵測模型、放寬部位框的門檻能不能提供方向證據。
- 修改：新增離線腳本 `scripts/part_detectors.py`；更正上一項「3D 上偵測不到部位框」的說法（實際上是鏡頭太短過不了門檻）；主程式未改；PLAN、README。
- 驗證：G04 上 NudeNet 的陰莖偵測率 16%，比現在的模型（22%）低；放寬門檻後的證據集中在陰莖超出畫面的特殊段落（使用者確認不計），不採用。`uv run pytest` 194 個通過、2 個略過。

## 2026-11-02 — 評估跨鏡頭的方向一致性（commit: `Record the scene consistency evaluation`）
- 目的：方向是現有資訊內最大的失分，評估同一支影片中動作型態相似的鏡頭能不能互相決定方向。
- 修改：新增離線腳本 `scripts/scene_consistency.py`；主程式未改；PLAN、README 的已知問題（G 系列上沒有部位框）。
- 驗證：相似度 ≥ 0.6 的鏡頭對 91% 方向相同，但錯的 74 個鏡頭中 60 個在 G 系列，那裡方向接近隨機、部位框只偵測到 9/130 個鏡頭，投票改對與改錯相近，不採用。`uv run pytest` 194 個通過、2 個略過。

## 2026-11-02 — 評估每一下的大小（commit: `Record the stroke size evaluation`）
- 目的：每一下的大小是相關係數上限最高的失分，評估能不能從現有的線索學出來。
- 修改：新增離線腳本 `scripts/stroke_size.py`（換位置的分解、特徵與嶺迴歸、聲音強度）；試做「行程大小拉齊」設定後還原，主程式未改；PLAN、README。
- 驗證：只修大小的上限是 dev r 0.464 → 0.597，但光流、部位框、聲音和人工腳本的深淺相關都在 ±0.2 以內；拉齊 dev r 只多 0.01，還會放大靜止鏡頭的動作，不採用。`uv run pytest` 194 個通過、2 個略過。

## 2026-11-01 — Web UI 開著頁面時 Ctrl+C 關不掉（commit: `Stop the web UI on Ctrl+C while a page is open`）
- 目的：開著網頁時按 Ctrl+C 伺服器不會結束，要重新整理頁面才會關閉。原因是 uvicorn 等所有連線結束才退出，而每個頁面的 Gradio heartbeat 串流不會自己結束。
- 修改：`webui.launch` 在 shutdown 時先停止接受連線再關閉現有連線，並設 2 秒的逾時備援；退出時設定取消旗標，讓處理中的工作停下；新增回歸測試。
- 驗證：`uv run pytest` 194 個通過、2 個略過；開著頁面時 Ctrl+C 0.3 秒退出（原本不會退出）。

## 2026-11-01 — 3 段 G 系列移到 dev，評估碎鏡頭（commit: `Move three G-series clips to dev and record the scene-cut test`）
- 目的：處理 holdout 中 G 系列鏡頭切得很碎、分數低的問題；需要可以調整的素材，所以把其中 3 段移到 dev。
- 修改：`validation.toml`（dev 16 段、holdout 10 段）；試做「切換後 2 秒內畫面回到原樣就不算切換」，好壞參半，程式未改；README、CLAUDE.md、PLAN。
- 驗證：`uv run pytest` 193 個通過、2 個略過（程式未改）；試做版 28 段 F1 0.705 → 0.707、r 0.488 → 0.483，B03 r −0.23；G 系列低分的主因是方向（35–40% 的時間相反），不是碎鏡頭。

## 2026-11-01 — 聲音提示預設關閉（commit: `Turn the sound-based inversion hint off by default`）
- 目的：「聲音起點在高點」的提示在保留組 holdout 標出的 14 個鏡頭全部方向正確，使用者選擇關閉。
- 修改：`pipeline.PipelineOptions.sound_hint`、`options.py` 的 `--sound-hint`（預設關閉）、`flip_by_asymmetry`；測試；README、PLAN。
- 驗證：`uv run pytest` 193 個通過、2 個略過；`--replay` 25 段 × 2 組動作逐點相同。

## 2026-11-01 — 保留組 holdout 與預覽的待確認鏡頭（commit: `Add a held-out clip group and mark scenes to check in the preview`）
- 目的：新增的 13 段素材固定為只做最後確認的保留組；在預覽中標出可能高低相反的鏡頭，方便逐一檢查與反轉。
- 修改：`validation.toml` 的 `holdout` 組與 `default_clips`（不加 `--clips` 只跑 dev、test）、`validate.clips`；`preview.player_html` 的 `checks`（黃色底色、「下一個待確認」按鈕與 `N` 鍵）、`webui.job_outputs`；測試；README、CLAUDE.md、PLAN。
- 驗證：`uv run pytest` 193 個通過、2 個略過。holdout 預設 F1 0.614、`r` 0.319（G 系列鏡頭切得很碎、偏低）；「可能高低相反」的提示在 holdout 標出的 14 個鏡頭全部方向正確，README 已註明。

## 2026-11-01 — 部位框判斷不再搜尋時間差（commit: `Judge the part sign at lag zero`）
- 目的：評估「AI 區域＋整個畫面」兩個方向線索時發現，部位框在 ±100 ms（10 fps 只有 ±1 個取樣）內取絕對值最大的相關，遇到快速行程時會挑到相反的方向：E02 兩個方向相反的輸出都被判為「一致」。雙線索本身不採用（兩者相反時 AI 區域對 72%，其他證據分不出來）。
- 修改：`tracking/parts.distance_sign` 預設只看 lag 0，附重現問題的測試；新增 `scripts/two_cues.py`；README 的基準表與已知問題、PLAN 的紀錄。
- 驗證：`uv run pytest` 192 個通過、2 個略過；`--replay` 25 段只有 E02、B03 改變，預設 dev F1 0.770 → 0.771、r 0.546 → 0.552，test 逐點相同。

## 2026-10-31 — testhost 的 CPU 上限 80%（commit: `Cap the CPU use of runs on the Windows test host`）
- 目的：使用者要求在 testhost 上跑的工作不讓 CPU 使用率超過 80%。量測發現 1 段 `--flow-workers 4` 就有中位數 96%，只減少工作數量做不到。
- 修改：新增 `scripts/remote_validate.ps1`，以處理器親和性限制可用的邏輯處理器，依使用者目前的用量決定段數，執行中每 5 秒依工作管理員的數字調整；CLAUDE.md 4.1 規定遠端的長時間工作一律用它啟動；PLAN 的紀錄。主程式沒有改。
- 驗證：`uv run pytest` 191 個通過、2 個略過；遠端 4 段長片平均 62%、56 次取樣中 1 次超過 80%（82%），分數和不限制時相同；遠端吞吐量估計約剩 6 成。

## 2026-10-31 — 新增系統流程圖（commit: `Add a system diagram of the pipeline`）
- 目的：讓人一眼看出從影片到 funscript 的流程、有哪些元件、哪些步驟可以選擇、哪些用到 AI、GPU、CPU。
- 修改：新增 `ARCHITECTURE.md`（三張 Mermaid 圖與元件一覽表）；README、PLAN、CLAUDE.md 加上連結，CLAUDE.md 規定流程改變時同時更新這份圖。程式沒有改。
- 驗證：`uv run pytest` 191 個通過、2 個略過；圖只手動核對語法，沒有實際渲染。

## 2026-10-31 — 量測 Hybrid 單獨與不用 AI 的分數（commit: `Measure Hybrid alone and the run without AI`）
- 目的：評估中「值得先量的」兩組：Hybrid 單獨的效果，以及不用 AI 和有 AI 的差距（接近的話 vLLM 可以變成選配）。
- 修改：`validation.toml` 新增 `hybrid`、`user-general`、`noai`、`noai-user` 四組設定；README 的驗證表與「AI 的幫助不穩定」的已知問題；PLAN 的紀錄。程式沒有改。
- 驗證：`uv run pytest` 191 個通過、2 個略過。25 段 F1 預設 0.731、只開 Hybrid 0.736、不用 AI 0.731；不用 AI 在 dev 較低（0.770 → 0.747）、test 較高（0.688 → 0.714），差別主要在方向。不改預設。

## 2026-10-31 — 修正停頓保持重複插入點與幾個小問題（commit: `Insert holds once and refuse --code with --replay`）
- 目的：清掉評估時列出的小問題：`--hold` 的停頓點重複插入；Web UI「取消」的訊息仍說 AI 分析中不能取消；`.gitignore` 列了仍被追蹤的檔案。驗證時另外發現 `validate --replay --code` 其實用目前的程式重算，`run.json` 卻記成 `--code` 的版本。
- 修改：`signal/process.insert_holds` 在停頓頭尾位置相同時不再插點（每個鏡頭和整支輸出各跑一次，第二次不再重複）；`validate.run_validation` 拒絕 `--replay` 同時給 `--code`，續跑的 replay 記錄目前的程式；`webui.cancel_run` 訊息、`.gitignore`、CLAUDE.md 第 4 節；新增 1 個測試、擴充 1 個。
- 驗證：`uv run pytest` 191 個通過、2 個略過；預設（不開 `--hold`）`--replay` 25 段 × 2 組逐點相同 50/50；開 `--hold` 時動作完全相同、只少了重複的點（一般模式 7515 → 7369 點），分數不變。

## 2026-10-31 — 部位框與快慢判斷改為預設開啟（commit: `Turn the part and asymmetry sign checks on by default`）
- 目的：兩者在沒有用來調整規則的第三批 12 段 F1 0.638 → 0.688，沒有一段變差，是目前最大、又還沒放進預設的改善。
- 修改：`pipeline.PipelineOptions` 與 `options.py` 的 `asym_sign`、`part_sign` 預設改為開啟，拿掉「實驗性」；移除和 `user` 相同了的 `--preset best`；`validation.toml` 改列 `default-nosign`、`user-nosign`；更新兩個測試、`scripts/sign_model.py`、README。
- 驗證：`uv run pytest` 190 個通過、2 個略過；`--replay` 新預設和之前加旗標的執行逐點相同 50/50，關閉兩者和之前的預設逐點相同 50/50。25 段平均 F1 0.693 → 0.731。

## 2026-10-31 — 還原未成年判斷（commit: `Restore the apparent-minor check`）
- 目的：使用者要求改回原來的。移除後 Hybrid 的 AI 較常回答看不到陰莖，使用者設定 F1 0.715 → 0.711（A06 0.530 → 0.444）。
- 修改：`git revert` 上一個 commit（`Remove the apparent-minor check`）的程式、測試與 README；PLAN 保留這次嘗試的發現，CLAUDE.md 4.1 保留遠端 `repo\vaild` 連結的說明。
- 驗證：`uv run pytest` 190 個通過、2 個略過（與移除前相同）；上次有差異的 A06、D03、G01、I01 以兩組設定重跑（`out/runs/restore`），和 `out/runs/new` 逐點相同 8/8。

## 2026-10-31 — README 補回「產生」按鈕的位置（commit: `Mention where the generate button is in the README`）
- 目的：整理 README 時漏掉了 `10ea752`（按鈕移到左欄最上方）寫的說明。
- 修改：README 使用步驟第 4 點。
- 驗證：只改文件。

## 2026-10-31 — 整理文件的分工（commit: `Split the documents by reader`）
- 目的：使用者要求移除評估中的冗餘。README、PLAN、CHANGELOG 合計約 16 萬字，同一組分數常寫三次，README 有 60 多列的歷史驗證表，PLAN 開頭還是最初的設計。
- 修改：README 改為使用說明——功能分組、只放最新的驗證表、已知問題每項一兩句（30 KB，原本 69 KB）；PLAN 開頭改為目前的架構與待解決的問題，最初的設計（第 1–8 節）刪除，原本 README 的歷史驗證表移到附錄；CLAUDE.md 寫明三份文件的分工；CHANGELOG 之後的條目只放摘要。
- 驗證：只改文件，`uv run pytest` 190 個通過、2 個略過。

## 2026-10-31 — 骨架模式改為選配套件，新增光流的合成回歸測試（commit: `Make the skeleton mode an optional extra`）
- 目的：使用者要求移除評估中的冗餘。PyTorch 等只有骨架模式用到，合成回歸測試也只測到骨架模式。
- 修改：`pyproject.toml` 把 ultralytics、lap、torch、torchvision 移到選配的 `pose`，直接列出原本間接安裝的 opencv-python、matplotlib、pillow（版本不變）；`tracking/pose.py` 沒有安裝時說明 `uv sync --extra pose`；`set-env.sh` 新增 `--pose`；新增 `tests/test_synthetic.py`（有紋理的合成影片與正確答案）與 1 個測試；README、PLAN、CLAUDE.md（回歸測試、testhost 的同步）同步。
- 驗證：沒有 PyTorch 時 `uv run pytest` 190 個通過、2 個略過；6 段 × 4 組設定完整執行逐點相同；`.venv` 1.9 GB → 874 MB。合成測試 F1 0.952、相關 0.906。

## 2026-10-31 — 移除聲音判定輔助（commit: `Remove the audio assist`）
- 目的：使用者要求移除評估中的冗餘。在 25 段上重算：只在 3–6 段觸發，B04、L01 的 F1 下降 0.03–0.08，四組設定的平均 F1 都下降。
- 修改：`signal/audio.py` 只留撞擊聲起點、相位與週期性；刪除 `pipeline.audio_assisted_actions`、`audio_assist` 選項與 `audio_spans`、4 個測試與 `scripts/make_synthetic_depth.py`（`set-env.sh` 不再檢查 ffmpeg，已沒有用到它的程式）；README、PLAN 同步。
- 驗證：`uv run pytest` 188 個通過、2 個略過；`--replay` 4 組 × 25 段和移除前逐點相同。開啟輔助時的 25 段平均 F1：一般模式 0.693 → 0.689、`--preset best` 0.747 → 0.743。

## 2026-10-31 — 移除單獨的加強目標判斷模式（commit: `Keep the genital analysis only inside the hybrid focus`）
- 目的：使用者要求移除評估中的冗餘。`--focus genital` 比一般模式差，它的 AI 呼叫只有在 Hybrid 中有用。
- 修改：`pipeline.py` 移除 `genital` 分析目標（`_apply_focus` 只給 Hybrid 用），選項表與 Web UI 只剩一般與 Hybrid；`tests/test_focus.py` 改為直接測試 Hybrid 的生殖器分析；README、PLAN 同步。
- 驗證：`uv run pytest` 191 個通過、2 個略過；一般模式與 Hybrid 各 3 段完整執行和移除前逐點相同。

## 2026-10-31 — 移除方向投票（commit: `Remove the sign vote`）
- 目的：使用者要求移除評估中的冗餘。`--sign-vote` 每個鏡頭多 6 次 AI 呼叫，效果不如快慢與部位框判斷。
- 修改：刪除 `ai/sign_vote.py`、投票用的提示詞與 schema、`pipeline._vote_signs` 與相關選項、結果欄位、CLI 與 Web UI 的摘要、選項表的項目與 9 個測試；README、PLAN 同步。
- 驗證：`uv run pytest` 191 個通過、2 個略過；`--replay` 4 組 × 25 段和移除前逐點相同。

## 2026-10-31 — 相關係數改為時間差 ±100 ms 內（commit: `Limit the correlation's lag to 100 ms`）
- 目的：使用者要求。±500 ms 的時間差讓整段方向相反的腳本仍有高相關（1.5 Hz 顛倒：0.96），評分看不出最主要的錯誤。
- 修改：`evaluate.py` 的 `compare` 預設 ±100 ms，舊算法存在 `Score.correlation_wide`；`compare` CLI、Web UI 摘要列出兩者；驗證執行器改存 `r100`／`r500`（讀取舊結果時自動改名），報表的 `r` 是新算法；兩個實驗腳本改用舊算法以重現紀錄。README（目前的驗證結果、已知問題）、PLAN、CLAUDE.md 同步。測試新增 2 個。
- 驗證：`uv run pytest` 201 個通過、2 個略過。動作與 F1 不變；25 段平均相關係數（舊 → 新）一般模式 0.527 → 0.496、`--preset best` 0.585 → 0.577，I01（整段相反）0.21 → −0.06。

## 2026-10-31 — 「產生」與「取消」按鈕移到最上方（commit: `Move the generate and cancel buttons to the top of the form`）
- 目的：使用者要求。按鈕原本在「產生」分頁長表單的最下方，要捲到底才能按。
- 修改：`webui.py` 把「產生 funscript」與「取消」移到左欄最上方（影片上傳欄上方），下方新增一列訊息顯示「取消」的結果（原本寫在表單底部，按鈕上移後看不到），按「產生」時清空。README 使用步驟、PLAN 進度同步更新。
- 驗證：`uv run pytest` 199 個通過、2 個略過；以 Chromium（Playwright）確認按鈕位置與取消訊息，沒有頁面錯誤。只改版面，不影響輸出，未重跑素材驗證。

## 2026-10-31 — 方向判斷的交叉驗證與待確認提示（commit: `Cross-validate the direction rules and list scenes to check`）
- 目的：評估中「應該要有的」最後一項：以留一支影片交叉驗證決定方向證據的組合方式，並讓使用者知道哪些鏡頭該檢查。
- 修改：新增 `scripts/sign_model.py`（從存下的分析計算每組鏡頭的快慢、聲音、部位框證據與真正的方向，比較規則、交叉驗證選的門檻與邏輯迴歸）。交叉驗證選出的就是目前的規則與門檻、迴歸較差，所以判斷不變。`pipeline.flip_by_asymmetry` 對維持原方向、但聲音起點在高點的組寫入 `sign_doubt` 與備註（`sign_doubt_audio` 0.4），`report.possibly_inverted` 一併列出，CLI 與 Web UI 摘要改為「可能高低相反（原因見備註）」；debug JSON 加上各方向檢查的旗標。測試新增 1 組（2 個）。
- 驗證：`uv run pytest` 199 個通過、2 個略過。`--replay` 4 組 × 25 段和完整執行逐點相同。方向正確的組：一般模式全部不翻 58/85、規則 73/85、迴歸最好 66/85；`--asym-sign --part-sign` 下一般模式提示 7 個鏡頭（4 個確實相反、1 個誤報），使用者設定 5 個（1 個相反）。

## 2026-10-31 — 驗證執行器、選項表、分析與輸出分開（commit: `Add a validation runner, one option table and re-renderable analyses`）
- 目的：使用者要求完成評估中「應該要有的」：驗證執行器、離線重播、Web UI 調參不重算、選項單一來源與設定組、可追溯的輸出（方向判斷另一個 commit）。
- 修改：新增 `validate.py`（CLI `validate`、`compare-runs`）與 `validation.toml`（25 段、dev／test 分組、設定組），結果多一欄 `r100`；`tracking/parts.py` 部位框的磁碟快取；新增 `options.py`（49 個設定的表），CLI `generate`／`render` 與 Web UI「產生」表單都由它產生，加上設定組（`--preset`、Web UI「設定組」）與 CLI `--scene-threshold`；`pipeline.py` 拆成 `analyze_video` 與 `render`（`generate` = 兩者），`--save-analysis`／`render`／`validate --replay` 重算輸出，Web UI 同一支影片只改輸出設定時沿用上次的分析；新增 `version.py`，metadata 記錄版本 0.2.0、程式碼雜湊、git commit、AI 模型與全部設定。測試新增 `test_options.py`、`test_validate.py` 與部位框快取、render 範圍、Web UI 沿用分析的測試。README、PLAN、CLAUDE.md（驗證改用執行器、選項表的規則、testhost 的做法）同步更新。
- 驗證：`uv run pytest` 197 個通過、2 個略過（略過的是未成年略過備註的兩個測試，維持原狀）。修改前的 pipeline 與新程式各跑 4 組設定 × 25 段，動作逐點相同 100/100；`--replay` 和完整執行逐點相同 100/100；Chromium 操作新表單正常。分數不變（dev / test，F1 / 忽略抖動 / r / r100）：一般模式 0.745 / 0.769 / 0.527 / 0.512、0.638 / 0.650 / 0.526 / 0.479；`--preset best` 0.783 / 0.838 / 0.587 / 0.587、0.708 / 0.712 / 0.583 / 0.567。第三批一般模式 F1 和 10-30 的紀錄差 0.002，原因是 AI 快取被覆寫，不是程式改變。

## 2026-10-31 — 評估整個流程的冗餘與缺少的部分（commit: `Evaluate the whole pipeline for redundancy and gaps`）
- 目的：使用者要求評估整個流程可以如何改進、有沒有冗餘、有沒有應該要有的。
- 修改：不改主程式。PLAN 新增評估紀錄與建議順序；README 更正未成年判斷的描述（提示詞固定回答 False，實際上不會略過任何鏡頭）與 Hybrid 的描述，已知問題新增「相關係數看不出整段方向相反」與 `--hold` 重複插點。
- 驗證：`uv run pytest` 171 個通過、2 個略過。1.5 Hz 整段顛倒的腳本 F1 0.00、相關 0.96；`out/v14_def_part`、`out/v15_def_part` 的相關平均（±500 / ±100 ms）0.529 / 0.524、0.531 / 0.504，I01 +0.21 → −0.06。25 段行程範圍辨識 185 個鏡頭中 156 個上限 80。

## 2026-10-30 — 評估鏡頭移動的估計方式（commit: `Evaluate camera-motion estimates for the flow component`）
- 目的：A06 第 0 鏡頭因為扣掉全畫面光流的中位數（當作鏡頭移動）而抓錯動作，評估其他估計方式。
- 修改：不改主程式。新增 `scripts/camera_motion.py`（用存下的光流場比較各估計方式取出的訊號與人工腳本的相關）；PLAN、README（已知問題、專案結構）記錄結果。
- 驗證：`uv run pytest` 171 個通過、2 個略過。25 段一般模式的區域 140 個鏡頭，平均 |r|：全畫面中位數（現行）0.676、不扣 0.659（改善 5、變差 13）、區域外格子 0.667、依頻譜集中度選擇 0.677；Hybrid 的兩種區域結果相同。現行方式整體最好，不修改。

## 2026-10-30 — 查明 A06、L01 第 0 鏡頭分數低的原因（commit: `Diagnose A06 and L01 first scenes`）
- 目的：這兩個鏡頭轉折點數量對得上但相關約 0.2，原本懷疑區域選錯；另記錄使用者說明的 F01 特殊情況。
- 修改：不改主程式。README 已知問題、PLAN 記錄原因與數字；README、PLAN 的 `--scene-center` 段補上不算 F01 的平均。
- 驗證：`uv run pytest` 171 個通過、2 個略過。A06：區域沒選錯，扣除畫面中位數（鏡頭移動）時把占滿畫面的主要動作扣掉，第一主成分變成 2.46 Hz 的小動作（r 0.15，不扣時 0.55）；關閉節奏濾波 0.22 → 0.25 無效。L01：輸出比人工腳本晚約 100 ms（對齊後鏡頭相關 0.69），25 段時間差中位數 0 ms，屬人工腳本的時間差。

## 2026-10-30 — 查明 `--scene-center` 讓 F01 變差的原因（commit: `Explain why scene centring lowers F01`）
- 目的：`--scene-center` 讓 F01 的相關係數 0.19 → 0.10，查原因並評估能否只在適合的鏡頭開啟。
- 修改：不改主程式。README 已知問題寫入原因，PLAN 記錄逐鏡頭分析與門檻實驗。
- 驗證：`uv run pytest` 171 個通過、2 個略過。F01 第 20–40 秒的光流慢速成分是和動作無關的漂移；57 個沒有節奏濾波的鏡頭，開啟後的相關變化有正有負、平均接近 0。依慢速 / 快速成分比例只對部分鏡頭開啟：25 段一般模式相關 0.556（全開）→ 0.560（≥ 1）→ 0.549（≥ 2），使用者設定 0.612 → 0.609 → 0.597，F1 差異 ≤ 0.004，不採用。

## 2026-10-30 — 慢動作保留高低（commit: `Centre tempo-less scenes on their whole range`）
- 目的：沒有節奏的鏡頭，位置以 4 秒視窗為中心，會把慢速大動作的高低抹平；上一項離線評估顯示改以整個鏡頭的範圍決定位置可以提高相關係數。
- 修改：`signal/process.py` 新增 `SignalParams.scene_center`，`to_actions` 在沒有節奏濾波的訊號改以整段 5–95% 範圍的中點為中心、範圍太大時縮進輸出範圍；CLI `--scene-center`、Web UI「慢動作保留高低（實驗性）」；`tests/test_signal.py` 新增測試。README（功能、參數、驗證結果、已知問題）、PLAN 同步。
- 驗證：`uv run pytest` 171 個通過、2 個略過。25 段（`--asym-sign --part-sign` 加上此選項）：一般模式 F1 0.730 → 0.730、相關 0.546 → 0.556；使用者設定 F1 0.747 → 0.744、相關 0.585 → 0.612。F01 相關下降（0.19 → 0.10），預設關閉。中途使用者暫停 testhost，全部改在本機跑。

## 2026-10-30 — 評估放大疊在大動作上的小行程（commit: `Evaluate amplifying small strokes on slow motion`）
- 目的：K01、A06、B04 的人工腳本在慢速大動作上疊了小行程，輸出沒有抓到；評估把光流的快速成分放大後再找轉折點是否有效。
- 修改：不改主程式。新增 `scripts/small_strokes.py`（在沒有節奏濾波的鏡頭以「慢動作 + 增益 × 快速成分」重找轉折點並評分，增益 1 為對照組）；PLAN、README（已知問題、專案結構）記錄結果。
- 驗證：`uv run pytest` 169 個通過、2 個略過。增益 2 和原輸出比，一般模式 13 段 F1 / 相關 / 忽略抖動的 F1 0.770 / 0.546 / 0.837 → 0.776 / 0.574 / 0.841、12 段 0.688 / 0.546 / 0.702 → 0.697 / 0.586 / 0.707；但對照組已有大部分的相關提升（來自以整個鏡頭範圍決定位置），放大本身只多 F1 約 0.003–0.015；K01 0.28 → 0.33。結論不採用；「沒有節奏的鏡頭以整個鏡頭範圍決定位置」列為待驗證的線索。

## 2026-10-30 — 診斷第三批素材的低分段（commit: `Diagnose the low-scoring clips of the third batch`）
- 目的：K01、A06、I01、B04 分數偏低，查明原因。
- 修改：不改主程式。新增 `scripts/scene_diag.py`（逐鏡頭診斷）；README 已知問題把「原因未查」改為各段的原因，PLAN 記錄分析數字。
- 驗證：`uv run pytest` 169 個通過、2 個略過。I01 整段方向相反（反轉後 F1 0.59 → 0.77）；K01 等是疊在大動作上的小行程沒有形成轉折點（降低最小動作幅度無效）；B04 慢速鏡頭是已知的停頓標法差異。

## 2026-10-30 — 部位偵測在背景進行、第三批驗證素材（commit: `Detect the part boxes in the background from the scene cut`）
- 目的：使用者新增 12 段驗證素材，用來檢查 `--asym-sign`、`--part-sign` 的規則在沒看過的素材上是否有效；並要求加速部位偵測。
- 修改：`pipeline.py` 新增 `PartScan`，鏡頭切分後就在背景偵測，和光流、AI 分析同時進行，`generate()` 在結束、取消或出錯時停止它；`flip_by_parts` 取用背景結果並取消被略過鏡頭的偵測。`tracking/parts.detect_span` 可中途停止。`tests/test_parts.py` 新增背景偵測與取消的測試。README（驗證結果、效能、已知問題）、PLAN 同步。
- 驗證：`uv run pytest` 169 個通過、2 個略過。新 12 段 F1 / 相關：一般模式 0.636 / 0.525 → `--part-sign` 0.676 / 0.531 → 兩者 0.688 / 0.546；使用者設定 0.664 / 0.565 → 兩者 0.708 / 0.583；`--asym-sign` 單獨幾乎沒有作用。25 段平均一般模式 0.692 → 0.730、使用者設定 0.715 → 0.747。B03 `--part-sign` 本機 158 → 119 秒、testhost 118 → 110 秒，輸出和修改前逐點相同。

## 2026-10-30 — 評估以陰莖框決定位置（commit: `Evaluate penis-box positions for the stroke depth`）
- 目的：相關係數偏低主要來自每一下的位置；陰莖框和人工腳本的相關很高，評估能否用它決定每一下的深淺。
- 修改：不改主程式。新增 `scripts/censor_position.py`（保留輸出時間、以陰莖框重新決定位置並評分）、`scripts/censor_stroke_size.py`（比較每一下行程大小的資訊量）；PLAN、README（已知問題、專案結構）記錄結果。
- 驗證：`uv run pytest` 168 個通過、2 個略過。13 段（基準 `--asym-sign --part-sign` 0.770 / 0.546 / 0.837）：以距離決定位置 0.748 / 0.498 / 0.811，各半混合 0.771 / 0.539 / 0.837，面積、長度更差；結論不採用。

## 2026-10-30 — 依部位框判斷方向（commit: `Flip scenes whose penis-vulva distance moves against the output`）
- 目的：動漫專用的部位偵測模型在評估中能指出正常位鏡頭的行程方向（距離大＝拔出＝高），使用者同意做成實驗性選項；並依使用者要求讓 testhost 用 GPU 偵測。
- 修改：新增 `src/funscript_gen/tracking/parts.py`（onnxruntime 直接跑 deepghs anime_censor_detection，不用會讓 numpy／OpenCV 降版的 imgutils；有 CUDA／DirectML provider 時自動用 GPU）；`pipeline.py` 新增 `flip_by_parts()` 與 `PipelineOptions.part_*`，反轉的鏡頭不再做快慢判斷與方向投票；CLI `--part-sign` / `--part-sign-threshold`、進度條、印出使用的裝置；Web UI 核取方塊、門檻滑桿、進度；debug JSON 的 `part_sign`；`pyproject.toml` / `uv.lock` 新增 onnxruntime、huggingface-hub；`tests/test_parts.py`（12 個測試）、`tests/test_flip.py` 的投票測試涵蓋部位框。CLAUDE.md 4.1 的同步指令改為遠端也換成 onnxruntime-directml。README、PLAN 同步。
- 驗證：`uv run pytest` 168 個通過、2 個略過。13 段 F1 / 相關 / 忽略抖動的 F1：一般模式 0.744 / 0.527 / 0.769 → `--part-sign` 0.758 / 0.529 / 0.812；`--asym-sign` 0.758 / 0.535 / 0.822 → 兩者 0.769 / 0.546 / 0.837；使用者設定 0.762 / 0.567 / 0.779 → 兩者 0.783 / 0.587 / 0.838；沒有一段素材的 F1 下降，舊 8 段不變。不開新選項時輸出和修改前逐點相同。testhost DirectML 每幀 23 ms（CPU 約 100 ms），框和 CPU 完全相同，B03 輸出和本機逐點相同。

## 2026-10-30 — 評估動漫專用的偵測模型（commit: `Evaluate anime detectors for the stroke direction`）
- 目的：使用者提供「分辨動漫圖片中人物」草案（imgutils 偵測 → SDPose／RTMW 骨架 → SAM），想知道能否加強識別。驗證素材全是動漫風格，YOLO-pose 偵測不到人，所以改測動漫專用的 imgutils 偵測模型，重點放在目前失分最多的行程方向。
- 修改：不改主程式。新增實驗腳本 `scripts/anime_det_dump.py`（每秒 1 幀跑 6 種偵測器）、`scripts/censor_dump.py`（指定時段高幀率跑 `detect_censors`）、`scripts/censor_sign.py`、`scripts/censor_flip.py`（和人工腳本比較、模擬依部位框反轉鏡頭）；imgutils 只用 `uv run --with` 暫時安裝。PLAN 進度記錄結果，README 的專案結構與已知問題同步。
- 驗證：`uv run pytest` 155 個通過、2 個略過。偵測率（13 段、每秒 1 幀）：人物 95%、頭 86%、陰莖框 42%。以「陰莖與陰道框的距離」決定方向：預設輸出 22 個有值的鏡頭中反轉 9 個、改對 8 個、改錯 0 個；以陰莖框面積：反轉 16 個、改對 12 個、改錯 3 個（都在 A01）。相對於 `--asym-sign` 的輸出，距離規則改對 4 個、改錯 2 個。主程式輸出不變，沒有重跑驗證。

## 2026-10-30 — numpy 的 BLAS 限制為 1 條執行緒（commit: `Run BLAS on one thread so it does not starve the flow workers`）
- 目的：testhost 同時跑多段時嚴重變慢（4 份 D01 每份 591 秒），本機也有浪費。原因是 OpenBLAS 在每個鏡頭的 SVD 時，在每個核心開執行緒忙等，和平行的光流搶 CPU。
- 修改：`src/funscript_gen/__init__.py` 在 numpy 載入前設定 `OPENBLAS_NUM_THREADS=1`（使用者已設定時沿用）；`tests/test_parallel.py` 新增測試（沒有修改時會失敗）。README 的效能說明、CLAUDE.md 4.1 的主機效能描述（testhost 跑光流其實比本機慢約 35%）、PLAN 同步更新。
- 驗證：`uv run pytest` 155 個通過、2 個略過（遠端 `tests/test_parallel.py` 7 個通過）。13 段有 AI 與 `--no-ai` 輸出和修改前逐點相同（26/26），F1 / 相關係數不變（0.744 / 0.527、0.709 / 0.473）。D01 本機 45 → 32 秒、遠端 76.5 → 44.9 秒；遠端 4 份同時跑 591 → 105 秒。

## 2026-10-30 — 有 AI 與不用 AI 的分數比較（commit: `Record the scores with and without the AI`）
- 目的：量化 AI 分析對結果的貢獻；文件中「不用 AI F1 0.04」是很早期的數字，需要用目前的版本重新測。
- 修改：只更新文件。README 驗證結果表新增 `--no-ai` 的 13 段／8 段平均與 A01 的新分數（舊數字標註為舊版），已知問題「不用 AI 時結果幾乎不能用」改寫為實測的差異；PLAN 進度新增比較結果與逐鏡頭分析。
- 驗證：`uv run pytest` 154 個通過、2 個略過。13 段預設一般模式：有 AI F1 0.744、相關係數 0.527（輸出和上一次逐點相同）；`--no-ai` F1 0.709、相關係數 0.473。長片差最多（A01 0.80 → 0.58、A04 0.78 → 0.50），B02 反而是不用 AI 較好（0.58 → 0.88）。

## 2026-10-30 — 工作規則加入第二台測試主機（commit: `Document the second test host in the agent rules`）
- 目的：新增一台測試主機 testhost（Windows、RTX 3070），讓之後的驗證能兩台平行跑；把用法與「只能用 `C:\Lab\funscript-gen`、測完要恢復原狀」的限制寫進專案規則，換 session 或換協作者都看得到。
- 修改：`CLAUDE.md` 新增 4.1 節（分工、環境隔離的 `env.ps1`、同步程式碼的指令、已知的 Windows 測試失敗），第 2 節清理步驟與第 5 節素材去向補上 testhost；PLAN 進度新增一項。不涉及程式碼，README 不需更新。
- 驗證：本機 `uv run pytest` 154 個通過、2 個略過。遠端：151 個通過、3 個失敗（Windows 平台限制）、2 個略過；`B01` 兩台輸出的動作逐點相同（F1 0.99、相關係數 0.912）；文件中的同步指令實際執行過，CUDA 版 torch 可用。

## 2026-10-30 — 光流同時鏡頭數依 CPU 核心數決定（commit: `Default the flow workers to half the CPU cores`）
- 目的：固定 4 個在 12 核的機器上沒有用滿 CPU。
- 修改：`pipeline.DEFAULT_FLOW_WORKERS`（核心數的一半，最多 8），`PipelineOptions.flow_workers`、CLI `--flow-workers`、Web UI 滑桿的預設值共用。README、PLAN 同步更新。
- 驗證：`uv run pytest` 154 個通過、2 個略過。A04 整個流程 4 / 6 個：34.7 / 27.1 秒；輸出不受執行緒數影響（`tests/test_parallel.py`、上一次回歸 26/26 相同）。

## 2026-10-30 — README：專案結構與 AI 請求數的說明（commit: `Describe the parallel steps and the AI concurrency in the README`）
- 目的：同步今天的修改到 README 的專案結構，並註明 AI 同時請求數改為 8 的影響範圍。
- 修改：只更新 README（專案結構、已知問題）。
- 驗證：不涉及程式，未重跑。

## 2026-10-30 — 加速與取消的最終回歸確認（commit: `Record the regression check of the speed-ups`）
- 目的：確認下午的加速與取消修改合起來不改變輸出。
- 修改：只更新文件（PLAN）。
- 驗證：`uv run pytest` 154 個通過、2 個略過。13 段一般模式與 Hybrid 的輸出和上午版本逐點相同（26/26），分數不變。

## 2026-10-30 — AI 分析回報進度、可在分析中取消（commit: `Report the AI step's progress and stop it on cancel`）
- 目的：AI 分析時進度條不動，取消也要等全部分析完成（長片可能好幾分鐘）。
- 修改：`pipeline.py` 新增 `_run_all()`，`_analyze_scenes`、`_detect_ranges`、`_pick_regions` 每完成一次呼叫就回報（`plan_scenes(..., progress)`，`"ai"` 階段回報完成比例），回報時中止會取消尚未送出的請求；Web UI 與 CLI 的 AI 進度條依比例前進。測試中替代這些函式的 lambda 改為接受新參數；`tests/test_parallel.py` 新增 1 個測試。README、PLAN 同步更新。
- 驗證：`uv run pytest` 154 個通過、2 個略過。A04 沒有快取時，AI 進行到 31% 時中止，19.3 秒停止。4 段素材（一般與 Hybrid）輸出和修改前逐點相同。

## 2026-10-30 — Web UI 取消按鈕（commit: `Let the web UI cancel a running job`）
- 目的：自主改進，處理 README 已知問題「處理中途無法取消」。
- 修改：`webui.py` 新增「取消」按鈕（`cancel_run()`，`queue=False`），進度回呼在下一次回報時中止並顯示「已取消」；`pipeline.generate()` 在等待光流時被中止（取消、Ctrl+C）會先停止光流再結束。`tests/test_parallel.py` 新增 1 個測試（沒有修改時失敗），`tests/test_webui.py` 新增 1 個測試。README 已知問題、功能表，PLAN 同步更新。
- 驗證：`uv run pytest` 153 個通過、2 個略過。無頭瀏覽器操作實際的 Web UI：按取消後 0.8 秒停止，之後的產生正常完成。不影響輸出。

## 2026-10-30 — 光流與 AI 分析重疊、AI 同時請求數可設定（commit: `Run the optical flow alongside the AI analysis`）
- 目的：自主改進。AI 答案沒有快取時（實際使用的情況），AI 階段比光流還久；光流和 AI 的答案無關，可以同時進行；vLLM 合併同時的請求，原本固定 4 個請求太保守。
- 修改：`pipeline.generate()` 在鏡頭切分後立即開始計算光流，AI 完成後再依區域算訊號（`FLOW_WAITING` 限制等待中的鏡頭數，AI 出錯時停止光流）；`config.Settings.vllm_concurrency`（`VLLM_CONCURRENCY`，預設 8），`PipelineOptions.ai_workers` 預設跟隨設定；CLI `--ai-workers`；Web UI「設定」分頁「同時請求數」；`.env.example` 加說明。`tests/test_parallel.py` 新增 2 個測試（AI 出錯時不會卡住、略過的鏡頭），`tests/test_config.py` 新增 1 個並檢查新變數的儲存。README 效能、參數表、`.env` 說明，PLAN 同步更新。
- 驗證：`uv run pytest` 151 個通過、2 個略過。13 段一般模式與 Hybrid 輸出和修改前逐點相同（26/26），合成影片相同。A04 沒有快取：一般模式 95.6 → 38.6 秒、Hybrid 123.3 → 53.7 秒。

## 2026-10-30 — 各鏡頭的光流平行計算（commit: `Compute the scenes' optical flow in parallel`）
- 目的：自主改進。處理時間幾乎全是光流，但只用到約 2 個核心；各鏡頭的光流彼此獨立。另外記錄以畫面放大／縮小判斷方向的評估（不採用）。
- 修改：`pipeline.generate()` 第二階段改為每個鏡頭各自解碼、以 `flow_workers` 個執行緒平行計算（骨架模式仍逐一處理）；`video/decoder.py` 的 `iter_frames` 從中間開始時，之前的幀也佔用取樣格子，取到的幀和從頭解碼相同；`PipelineOptions.flow_workers`（4）、CLI `--flow-workers`、Web UI「同時計算光流的鏡頭數」。新增 `tests/test_parallel.py`（2 個測試，解碼的測試在舊寫法下失敗）。README 效能、參數表，PLAN 同步更新。
- 驗證：`uv run pytest` 148 個通過、2 個略過。13 段一般模式與 Hybrid 輸出和修改前逐點相同（26/26），合成影片（`--mode pose`）相同。A04 整個流程：1 / 4 / 8 個執行緒 70.5 / 33.3 / 27.4 秒，4 個加 `--flow-width 320` 20.5 秒。

## 2026-10-30 — 記錄使用者設定下的光流寬度測試（commit: `Record the narrower-flow test with the web UI settings`）
- 目的：使用者用 Hybrid 與自己的 Web UI 設定產生，確認 `--flow-width 320` 在這個設定下的效果。
- 修改：只更新文件（README 驗證表、PLAN）。
- 驗證：使用者設定（Hybrid、保留停頓、長行程補點、高頻縮小 2→3 Hz），13 段 F1 / 相關 / 忽略抖動的 F1：480 → 320 為 0.762 / 0.567 / 0.779 → 0.765 / 0.563 / 0.782；加 `--asym-sign` 0.770 / 0.583 / 0.824 → 0.774 / 0.569 / 0.826。

## 2026-10-30 — 光流計算寬度選項（commit: `Add an option to compute optical flow on a narrower frame`）
- 目的：自主改進。光流是處理時間的主要部分；評估更快的算法與較低的解析度。
- 修改：`tracking/flow.py` 的 `FlowTracker` 新增 `flow_width`（在較窄的畫面上計算，再換算回 480 寬的格子與像素；等於 480 時走原本的路徑）；`pipeline.PipelineOptions.flow_width`（預設 480）；CLI `--flow-width`（160–480）；Web UI「光流計算寬度」滑桿。`tests/test_flow.py` 新增 1 個測試。README 參數表、CLI 範例、驗證表、已知問題（效能），PLAN 記錄 DIS 光流（不採用）與解析度的評估。
- 驗證：`uv run pytest` 146 個通過、2 個略過。預設（480）輸出逐點相同（A04）。`--flow-width 320`：A04 整個流程 70.3 → 33.5 秒；13 段 F1 / 相關 / 忽略抖動的 F1 一般模式 0.744 / 0.527 / 0.769 → 0.698 / 0.557 / 0.723（B02 整段方向翻成相反：0.58 → 0.02，其他素材 ±0.04 以內），Hybrid 0.759 / 0.558 / 0.783 → 0.764 / 0.549 / 0.793。方向不穩的影片換解析度可能換方向，所以預設不變。DIS 光流離線 13 段 F1 0.744 → 0.653，不採用。

## 2026-10-30 — 以聲音確認行程方向（commit: `Back the stroke-sign check with the sound's onsets`）
- 目的：自主改進。方向相反仍是最大的誤差來源；之前的線索都來自畫面。撞擊聲通常在插入到底前一刻，和鏡頭角度無關。離線分析發現插入類鏡頭的聲音起點幾乎都在人工腳本低點前約 40°，但口交鏡頭（與 B01）在頂端，所以聲音只用來確認快慢判斷，不單獨決定反轉。
- 修改：`signal/audio.py` 新增 `onset_phase()`（聲音起點在訊號週期中的位置），`onset_envelope()` 改為每 60 秒一段邊解碼邊計算（長片不再需要大量記憶體）；`pipeline.flip_by_asymmetry()` 接收包絡線，聲音起點落在高點（< −0.3）的鏡頭門檻從 0.5 降到 0.2，記錄 `ScenePlan.audio_sign`（debug JSON）；新增 `PipelineOptions.asym_audio`（預設開啟）/ `asym_audio_threshold` / `asym_audio_min` / `asym_audio_phase`；CLI `--asym-audio/--no-asym-audio`、`--asym-audio-threshold`；Web UI 快慢判斷設定列加「以聲音確認」與門檻滑桿。`tests/test_audio.py` 新增 3 個、`tests/test_chunks.py` 新增 2 個測試，`tests/test_webui.py` 檢查新設定的預設值。README 功能表、參數表、CLI 範例、驗證表、已知問題，PLAN 同步更新（含不採用的每支影片校準、聲音判斷靜止片段）。
- 驗證：`uv run pytest` 145 個通過、2 個略過。預設（`--asym-sign` 關閉）13 段輸出與修改前逐點相同。`--asym-sign`，F1 / 相關 / 忽略抖動的 F1：一般模式 13 段 0.752 / 0.528 / 0.804 → 0.758 / 0.535 / 0.822（舊 8 段 0.892 / 0.662 → 0.891 / 0.665）；Hybrid 0.763 / 0.558 / 0.815 → 0.767 / 0.566 / 0.829；使用者的 Web UI 設定 0.766 / 0.564 / 0.810 → 0.770 / 0.583 / 0.824。新翻轉的 9 個鏡頭中 7 個改對（B03、D02、E02），A01 第 6 段（人工腳本相關 +0.17）翻錯。

## 2026-10-30 — 記錄方向問題剩下的空間（commit: `Record how much of the stroke-sign gap is left`）
- 目的：作為之後是否投入新資源（更多正常位素材、本地偵測模型）的依據。
- 修改：只更新文件（PLAN）。
- 驗證：離線以最終輸出計算：每個鏡頭方向都正確時 13 段忽略抖動的 F1 上限 0.858；預設 0.769、開啟 `--asym-sign` 0.804、再加 `--sign-vote` 0.814。

## 2026-10-30 — 最終回歸確認（commit: `Record the final regression check of the day`）
- 目的：今天後半的修改（低幀率修正、提示、投票組合、`--invert` 相關）都只影響非預設的路徑，以目前版本重跑確認預設輸出沒有改變。
- 修改：只更新文件（PLAN 後續條目的標題）。
- 驗證：`uv run pytest` 140 個通過、2 個略過。13 段預設一般模式與 Hybrid 重跑，輸出與「沒有人的鏡頭停在最高點」驗證時（`out/v5_def`、`out/v5_hyb`）逐點相同：一般 0.745 / 0.527 / 忽略抖動 0.769、Hybrid 0.759 / 0.558 / 0.783。

## 2026-10-30 — 方向投票以輸出方向計票（commit: `Vote on the output direction when the output is inverted`）
- 目的：自我檢查時發現，方向投票（既有的實驗性功能）以反轉前的方向計票，和 `--invert` 一起用時，投票決定的翻轉會被整支反轉抵銷，得到錯的方向；和上一項快慢判斷的修正一致，改以最終輸出的方向判斷。
- 修改：`pipeline.py` 的 `_vote_signs()` 在 `invert` 時把訊號的高點與低點互換再請 AI 量測。`tests/test_flip.py` 新增 1 個測試（先寫成能重現問題的測試）。README 功能表、PLAN 同步更新。
- 驗證：`uv run pytest` 140 個通過、2 個略過。沒有 `--invert` 時行為不變。E02 以 `--invert --sign-vote` 產生：計票 1 比 3 不翻，輸出與只開 `--sign-vote`（3 比 1 翻轉）逐點相同（F1 0.64、相關 0.346）。

## 2026-10-30 — README：更正快慢判斷修正的素材（commit: `Clarify which clips the stroke-speed check fixes in the README`）
- 目的：README 已知問題寫「B02 的快慢不對稱和方向無關，修不了」，但一般模式下 B02 有 1 個鏡頭被正確反轉。
- 修改：只更新 README 的已知問題措辭。
- 驗證：不涉及程式，未重跑。

## 2026-10-30 — 快慢判斷以輸出方向為準、停住的鏡頭不受反轉影響（commit: `Judge the asymmetry on the output and keep rests at the top through flips`）
- 目的：自我檢查時發現和 `--invert` 一起用的兩個問題。(1) 快慢判斷以反轉前的方向計算，`--invert` 時會把反轉後已經正確的鏡頭再翻錯、提示也指錯鏡頭；(2) 停在最高點的鏡頭跟著反轉停到最低點，而人工腳本此時停在 99。`--invert` 在本專案是修正動作方向用的，「沒有人時停在最高位置」是慣例而不是方向判斷。
- 修改：`pipeline.py` 的 `flip_by_asymmetry()` 在 `invert` 時以反轉後的方向判斷；`finalize()` 中停住的鏡頭不受 `--invert` 與逐鏡頭反轉影響。`tests/test_chunks.py` 新增 1 個測試，`tests/test_rest.py` 改為檢查停住的鏡頭不反轉（先寫成能重現問題的測試）。README 功能表、已知問題，PLAN 同步更新。
- 驗證：`uv run pytest` 138 個通過、2 個略過。預設（沒有 `--invert`）輸出不變（`vaild/A02` 與上一版逐點相同）。D02 以 `--invert --asym-sign` 產生，F1 / 相關 / 忽略抖動的 F1 0.49 / 0.085 / 0.81 → 0.49 / 0.463 / 0.81（只開 `--asym-sign` 0.47 / 0.319 / 0.72）。

## 2026-10-30 — 摘要列出可能高低相反的鏡頭（commit: `List scenes that may be inverted in the summary`）
- 目的：「可能高低相反」的提示原本只寫在鏡頭表的備註，不顯眼；另外記錄使用者設定下的驗證結果。
- 修改：`pipeline.py` 新增 `ScenePlan.asym_hint`（關閉 `--asym-sign` 時被提示的鏡頭）；`report.py` 新增 `possibly_inverted()`；`webui.py` 的摘要列出尚未反轉的這類鏡頭（手動反轉後就不再列出）；`cli.py` 產生後也列出並給出對應的 `--flip-scenes`。`tests/test_webui.py` 新增 1 個測試。README 功能表與驗證表、PLAN 同步更新（含使用者設定的比較、Hybrid 的節奏濾波測試）。
- 驗證：`uv run pytest` 137 個通過、2 個略過。只改顯示，不影響偵測與輸出：`vaild/B02` 的輸出與上一版逐點相同，CLI 列出第 3 段。使用者的 Web UI 設定（Hybrid、保留停頓、長行程補點、高頻縮小 2→3 Hz）13 段 F1 / 相關 / 忽略抖動的 F1：今天修改前 0.761 / 0.531 / 0.779 → 新預設 0.761 / 0.566 / 0.779 → 加 `--asym-sign` 0.765 / 0.564 / 0.810。

## 2026-10-30 — 評估：幅度、節奏濾波、Hybrid 候選區域、改選主成分（commit: `Record the amplitude, rhythm-check, hybrid-pick and component tests`）
- 目的：自主改進。分析顯示相關係數偏低主要來自位置（行程長短與高低）而不是時間，另外長片仍有漏點的鏡頭；離線測試幾個可能的改法。
- 修改：只更新文件（PLAN 評估紀錄），主程式未修改。
- 驗證：以存好的光流場重建訊號、只重跑後處理（重現主程式 13 段 0.744 / 0.529，主程式 0.745 / 0.527）。滿行程基準、行程倍率、填滿行程、鏡頭基準的各種設定，13 段相關最多 +0.009；節奏濾波的行程頻率檢查先去掉漂移、集中度門檻 0.4，都在 +0.003 以內；Hybrid 套用候選區域再確認估計 13 段 0.759 / 0.558 → 0.743 / 0.523（B02 換區域後方向反了）；依週期性改選其他主成分不比現行好（上限 0.784 / 0.570 主要來自方向）。都不採用。

## 2026-10-30 — 依快慢判斷方向：關閉時提示、與方向投票的組合（commit: `Hint at inverted scenes and keep asymmetry flips out of the sign vote`）
- 目的：(1) 選項預設關閉時，使用者看不到哪些鏡頭可能高低相反；(2) 和 `--sign-vote` 同時開啟時，已依快慢改對的鏡頭會投「不翻」，稀釋整支影片的投票（B03 從 10 比 1 翻轉變成 7 比 4 不翻），兩個選項一起開反而比只開投票差。
- 修改：`pipeline.py` 的 `flip_by_asymmetry()` 在選項關閉時，對超過門檻的鏡頭只在備註寫「可能高低相反」；新增 `ScenePlan.asym_flipped`，`_vote_signs()` 跳過已依快慢反轉的鏡頭（不投票、不跟著整支翻轉）。`webui.py` 選項說明更新；`tests/test_chunks.py` 檢查提示，`tests/test_flip.py` 新增 1 個測試。README 功能表、CLI 範例、驗證表、已知問題同步更新；PLAN 記錄結果。
- 驗證：`uv run pytest` 136 個通過、2 個略過。預設輸出（B02、B03、D02、E02、F01）與修改前逐點相同，提示出現的鏡頭和開啟時會反轉的鏡頭相同。一般模式 13 段 F1 / 相關 / 忽略抖動的 F1：只開投票 0.752 / 0.548 / 0.814；兩者同時開啟，修改前 0.753 / 0.532 / 0.805 → 修改後 0.754 / 0.549 / 0.814（B03 6 比 0 翻轉，忽略抖動的 F1 0.91）；舊 8 段在各種組合下都不變。

## 2026-10-30 — 修正低分析幀率時的不對稱計算錯誤（commit: `Cap the asymmetry low-pass below the Nyquist frequency`）
- 目的：上一個 commit 加入的 `fall_rise_asymmetry()` 固定以 6 Hz 低通，分析幀率 ≤ 12（Web UI 滑桿允許 5–60、CLI `--fps`）時超過奈奎斯特頻率，`butter` 丟出例外；而且每個鏡頭都會計算不對稱值，所以不論是否開啟 `--asym-sign`，整個產生流程都會失敗。
- 修改：`signal/process.py` 的低通頻率上限改為 0.45 × 幀率（與節奏濾波相同）。`tests/test_signal.py` 新增 1 個重現問題的測試（10 fps）。
- 驗證：`uv run pytest` 135 個通過、2 個略過。`vaild/A02` 以 `--fps 10` 產生：修正前失敗（ValueError），修正後正常。30 fps 時低通頻率不變（6 Hz < 13.5 Hz），驗證素材的輸出不受影響。

## 2026-10-30 — 實驗性：依行程快慢判斷方向（commit: `Add an experimental stroke-sign check from rise and fall speeds`）
- 目的：自主改進，針對正常位素材高低相反的問題。人工腳本 83% 的鏡頭往下（插入）比往上快，光流訊號在不對稱明顯時也一樣；「往上比往下明顯快」代表方向相反。這個特性和鏡頭角度無關，和之前試過的位置類方法不同。
- 修改：`signal/process.py` 新增 `fall_rise_asymmetry()`，峰谷交替抽成 `_alternate()`（`find_strokes` 共用，行為不變）；`pipeline.py` 新增 `flip_by_asymmetry()`（分段對齊之後執行，同一長鏡頭中型態相同的分段一起判斷）、`PipelineOptions.asym_sign` / `asym_sign_threshold` / `asym_sign_min_strokes`、`ScenePlan.asym`；`report.py` debug JSON 加 `asym`；`cli.py` 新增 `--asym-sign/--no-asym-sign`、`--asym-threshold`；`webui.py` 新增「依行程快慢判斷方向（實驗性）」核取方塊與門檻滑桿。`tests/test_signal.py` 新增 1 個、`tests/test_chunks.py` 新增 3 個測試，`tests/test_webui.py` 檢查新的滑桿切換。README 功能表、參數表、驗證表、已知問題同步更新；PLAN 記錄分析與驗證。
- 驗證：`uv run pytest` 134 個通過、2 個略過。預設關閉；關閉時只多記錄每個鏡頭的不對稱值，輸出不變（`find_strokes` 的重構不改變行為）。開啟時（主程式，8B、AI 快取，F1 / 相關 / 忽略抖動的 F1）：一般 13 段 0.745 / 0.527 / 0.769 → 0.752 / 0.528 / 0.804，Hybrid 0.759 / 0.558 / 0.783 → 0.763 / 0.558 / 0.815，舊 8 段兩種模式都完全相同；B03 忽略抖動的 F1 0.47 → 0.80、D02 0.64 → 0.72（Hybrid 0.62 → 0.70）、B02 0.59 → 0.63（一般模式）。反轉的 11 個鏡頭中，人工腳本有明顯動作的全部改對，只有 B03 第 14 段（人工腳本幾乎不動）+0.14 → −0.22。B03 整段相關 0.481 → 0.415 是整段相關取 ±500 ms 最佳延遲的特性，10 秒視窗零延遲相關 −0.28 → +0.16（13 段平均 0.234 → 0.297）。

## 2026-10-30 — 沒有人的鏡頭停在最高點（commit: `Hold scenes with nobody in the picture at the top`）
- 目的：自主改進。分析發現整段相關係數受人工腳本「靜止」的片段影響很大：靜止的 4 秒視窗 34 個中有 25 個停在 90–100，輸出在這些地方仍有光流雜訊造成的動作。一般的靜止判定分不開，但 AI 場景分析回答 0 人的鏡頭幾乎都是靜止（靜止 14 個、有動作 1 個，0.3 秒）。
- 修改：`pipeline.py` 新增 `PipelineOptions.rest_empty`（預設開啟）、`ScenePlan.rest`、`_sees_nobody()`；`plan_scenes` 在一般分析（或 Hybrid 的一般分析）回答 0 人時把鏡頭標為略過並停住（不呼叫行程範圍辨識、不算光流，手動 `--roi` 時不執行）；`finalize` 在這些鏡頭的開始與結束各輸出一個最高點。`report.py` 鏡頭表模式欄顯示 `rest`、debug JSON 加 `rest`；`cli.py` 新增 `--rest-empty/--no-rest-empty`、列表顯示 `rest`；`webui.py` 新增「沒有人的鏡頭停在最高點」核取方塊（納入記住的設定）。新增 `tests/test_rest.py`（6 個測試）。README 功能表、參數表、驗證表、已知問題同步更新，並移除驗證表後殘留的一份舊表格；PLAN 記錄分析與驗證。
- 驗證：`uv run pytest` 130 個通過、2 個略過。主程式（8B、AI 快取），F1 / 相關：一般 13 段 0.745 / 0.487 → 0.745 / 0.527、舊 8 段 0.894 / 0.649 → 0.893 / 0.662；Hybrid 13 段 0.759 / 0.520 → 0.759 / 0.558、舊 8 段 0.888 / 0.649 → 0.888 / 0.660。相關上升：B03 0.320 → 0.481、D02 0.079 → 0.266、E02 0.206 → 0.294、A04 0.352 → 0.425、A01 0.404 → 0.432；下降：B02 0.276 → 0.264（Hybrid 0.732 → 0.710，片尾 0.1 秒的鏡頭改為停住，滿行程基準跟著變）；E01 F1 0.86 → 0.85（片尾 0.3 秒的鏡頭，人工腳本有 2 個點）。合成影片（`--mode pose`）0.97 / 0.835 不變。

## 2026-10-29 — 評估：轉折點標在停頓結尾、以補點代替停頓保持（commit: `Record the rest-end and curve follow-up tests`）
- 目的：上一項列出的兩個後續，使用者同意繼續。
- 修改：只更新文件（PLAN 評估紀錄、README 已知問題），主程式未修改。
- 驗證：離線以 `out/v4_def` 與存好的光流場計算。(1) 方向正確鏡頭中 3157 個配對的轉折點，150 ms 內命中率標在極值都高於標在停頓結尾（300–600 ms 的停頓 0.86 對 0.46），不採用。(2) 停頓保持關閉時加 `--curve`：13 段 F1 / 相關 0.745 / 0.488 → 0.750 / 0.478，B02、F01 相關下降，維持預設關閉。`uv run pytest` 124 個通過、2 個略過。

## 2026-10-29 — 停頓保持改為預設關閉、修正評分的峰谷判斷（commit: `Turn the pause hold off by default and fix held-peak scoring`）
- 目的：使用者要求處理改進方向第 5 項（慢行程召回率偏低，原因未查）。調查發現 1–2 Hz 偏低主要是方向相反；1 Hz 以下多半是人工腳本把轉折點標在停頓結尾；而「動作點相隔超過 1 秒就停住」的停頓保持會把 2–3 秒一趟的慢行程變成方波，拉低相關係數。另外評分把停頓保持在峰頂的結尾點判成谷。使用者選擇停頓保持預設關閉。
- 修改：`evaluate._extrema` 平台結尾的點依之後的走向判斷峰谷；`signal/process.py` 的 `SignalParams` 新增 `hold`（關閉），`to_actions` 只在開啟時插入停頓保持；`pipeline.finalize` 同樣；CLI `--hold/--no-hold`、`--hold-after-ms`；Web UI「停頓時保持原位」核取方塊與門檻滑桿，納入記住的設定。`tests/test_signal.py` 新增 2 個測試（停頓結尾算峰；慢行程預設不停住），`tests/test_webui.py` 檢查新的核取方塊。README 功能表、使用方式、參數表、驗證表（改用修正後評分，舊列標示「舊評分」）、已知問題同步更新。
- 驗證：`uv run pytest` 124 個通過、2 個略過。評分修正對同一份輸出：一般 13 段 F1 0.750 → 0.745、Hybrid 0.764 → 0.760。主程式（修正後評分，F1 / 相關）：一般 13 段 0.745 / 0.435 → 0.745 / 0.487、舊 8 段 0.888 / 0.597 → 0.894 / 0.649；Hybrid 13 段 0.760 / 0.466 → 0.759 / 0.520、舊 8 段 0.883 / 0.591 → 0.888 / 0.649。F01 F1 0.54 → 0.51；合成影片（`--mode pose`）0.97 / 0.851 → 0.97 / 0.835（真值有靜止停頓）。

## 2026-10-29 — 評估：剪接後的鏡頭比對動作型態對齊方向（commit: `Record the cross-cut sign alignment test`）
- 目的：改進方向討論後，使用者同意先做第 2 項：把長鏡頭分段的方向對齊延伸到剪接後的鏡頭。
- 修改：只更新文件（PLAN 評估紀錄、README 已知問題），主程式未修改。
- 驗證：`uv run pytest` 122 個通過、2 個略過。離線以 14 段一般模式與 hybrid 輸出、存好的光流場計算。方向實際相反的剪接鏡頭對，型態相似度只預測出 6/19（hybrid 3/17），它們的動作型態和方向正確的鏡頭相同。鏡頭層級模擬：一般模式 71/101 → 最好 75/101（舊素材 62 → 60），hybrid 69/96 → 最好 76/96，改善只在個別門檻出現、兩種模式不一致。r ≤ −0.3 的鏡頭在 ±300 ms 內取最佳延遲仍有 25/30 為負，是真的方向相反。不採用。

## 2026-10-29 — 評估：以 32B 重測原生影片輸入判斷方向（commit: `Record the 32B native-video stroke-sign test`）
- 目的：使用者把 vLLM 換成 Qwen3-VL-32B（AWQ），重測上一項。
- 修改：只更新文件（PLAN 評估紀錄、README 已知問題），主程式未修改。
- 驗證：紅球位移 14% 時能分出上下（8B 不行），但真實素材的方向試跑仍與內容無關（倒著播也相同），片段正確率 18/36、16/30、8/20；中性問法數行程次數與光流節奏的相關係數 0.07。不採用。

## 2026-10-29 — 評估：以原生影片輸入判斷行程方向（commit: `Record the native-video stroke-sign test`）
- 目的：使用者提議每個鏡頭取一部分片段，用 VLM 的原生影片輸入判斷方向，修正上下顛倒；並為此在 vLLM 開啟影片輸入。
- 修改：只更新文件（PLAN 評估紀錄、README 已知問題），主程式未修改。
- 驗證：離線實驗（8B，B03、A03 各 3 個鏡頭、36 段半個行程的片段）：三種問法、整個畫面或裁切，答案都與畫面內容無關（倒著播也相同），正確率在隨機水準；2 秒片段數行程次數，模型大多回答 0–2 次（光流約 2–6 次）。不採用。

## 2026-10-29 — 移除登入帳號（commit: `Remove web UI login for single-user use`）
- 目的：使用者表示這個軟體設計為單人使用，要求移除帳號功能。
- 修改：刪除 `src/funscript_gen/auth.py`、`tests/test_auth.py`；`webui.py` 移除「設定」分頁的「登入帳號」、頁面頂端的預設帳號提醒，`create_app()` / `launch()` 不再接受登入參數；`cli.py` 的 `webui` 移除 `--auth/--no-auth`、`--auth-file`；`start-webui.sh` 移除 `WEBUI_AUTH_ENABLED`、`WEBUI_ALLOW_NO_AUTH`，開放區網時改為只顯示警告、不再拒絕啟動；`tests/test_webui.py` 改為確認不需登入即可存取。`.gitignore` 保留 `.webui-auth.json`（避免舊檔被提交）。README、PLAN 同步更新。
- 驗證：`uv run pytest` 122 個通過、2 個略過（少的 7 個是刪除的登入測試）；以 `start-webui.sh` 實際啟動，`/config` 不需登入回應 200。未改動偵測與輸出邏輯，不需重跑素材驗證。

## 2026-10-29 — 評估：以「誰在動」決定行程方向（commit: `Record the who-moves stroke-sign test`）
- 目的：使用者提議以互動的一方有沒有動判斷體位，再以動的一方「靠近對方＝低」決定方向，問這樣是否有效。
- 修改：只更新文件（PLAN 評估紀錄、README 已知問題），主程式未修改。
- 驗證：離線以 14 段素材的 hybrid 輸出與存好的光流場計算，未重跑主程式。「誰在動」版本與兩框距離版本在 64 個可算的鏡頭中方向完全相同。|r| ≥ 0.3 的 92 個鏡頭：現行規則 67/92、加權平均相關 0.355；新規則 71/92、0.354（正常位 8/32 → 22/32，其他素材 59/60 → 49/60）。加信心門檻或整支影片投票都沒有明顯優於現有 `--sign-vote`（82/92、0.484），不採用。`uv run pytest` 129 個通過、2 個略過。

## 2026-10-29 — 節奏濾波先確認節奏、評分忽略抖動（commit: `Check the stroke rate before band-passing an unclear tempo`）
- 目的：使用者要求處理快速動作召回率低（選項 3）。調查後發現主因不是動作太快：B03、D02 的人工腳本疊了大量細小抖動；真正抓不到的 F01 是節奏濾波鎖定了錯的節奏（0.82 Hz，實際約 1.8 Hz），把行程濾掉。
- 修改：`signal/process.py` 的 `dominant_tempo` 集中度分母改從 `min_hz / 2` 起算（不計入漂移）；新增 `stroke_rate()`、`SignalParams.rhythm_sure_share`（0.8）、`rhythm_rate_tol`（0.7–1.4），集中度 0.5–0.8 時行程頻率要和節奏一致才濾波。`evaluate.py` 新增 `drop_wiggles()`、`WIGGLE`；`cli.py` 的 `compare` 多印 `F1(strokes)`；`webui.py` 摘要顯示忽略抖動的 F1。`tests/test_signal.py` 新增 2 個測試。README 功能表、驗證表、已知問題同步更新。
- 驗證：`uv run pytest` 129 個通過、2 個略過。一般模式 13 段平均 F1 / 相關 0.727 / 0.430 → 0.750 / 0.435（F01 0.29 → 0.56、E01 0.83 → 0.86；D02 相關 0.099 → 0.083、A03 0.515 → 0.509），舊 8 段 0.885 / 0.592 → 0.889 / 0.598。Hybrid 13 段 0.744 / 0.463 → 0.764 / 0.466；D01 hybrid 0.84 → 0.82（一個 3 Hz 鏡頭的行程頻率檢查沒過）。

## 2026-10-29 — 逐鏡頭反轉與實驗性方向投票（commit: `Flip single scenes by hand and add an experimental sign vote`）
- 目的：使用者選擇先做逐鏡頭手動反轉，並把方向投票做成預設關閉的實驗性選項；要求預覽下方有「反轉」按鈕與鏡頭編號，鏡頭表可以直接反轉並立即修改 funscript。
- 修改：`pipeline.py` 新增 `ScenePlan.flipped`、`finalize()`、`refinalize()`、`toggle_flip()`、`flipped_scenes()`、`_vote_signs()`，`PipelineOptions.flip_scenes`、`sign_vote`（關閉）及投票參數，`PipelineResult.sign_vote`；新增 `ai/sign_vote.py`；`ai/prompts.py` 新增 `VisibleLength`、`LENGTH_PROMPT`；`report.py` 鏡頭表新增「反轉（點擊切換）」欄、debug JSON 加入 `flipped`；`cli.py` 新增 `--flip-scenes`、`--sign-vote/--no-sign-vote`；`preview.py` 資訊列顯示鏡頭編號與是否反轉、重建後回到原本時間，並修正隱藏分頁中寬度 0 的繪圖錯誤；`webui.py` 新增 `Job` / `PreviewJob` 狀態、鏡頭表點擊反轉、預覽下方「反轉」按鈕（兩個分頁）、「方向投票（實驗性）」核取方塊。新增 `tests/test_flip.py`（12 個），`tests/test_webui.py` 新增 5 個。README 功能表、使用方式、參數表、驗證表與已知問題同步更新。
- 驗證：`uv run pytest` 127 個通過、2 個略過；headless Chromium 實際操作頁面通過（表格反轉／還原、播放器按鈕、預覽分頁）。預設輸出在 11 段素材上與修改前逐點相同；E02、B03、D02 因 AI 回答不同而與上一輪有差異（見 PLAN）。`--sign-vote` 翻轉 E02（0.61 / 0.059 → 0.63 / 0.351）、B03（0.41 / 0.262 → 0.43 / 0.279）、D02（0.47 / 0.099 → 0.49 / 0.171），其他 10 段不變；13 段逐鏡頭正負號正確 66/96 → 83/98。

## 2026-10-29 — 新素材測試：行程方向（commit: `Record stroke-sign tests on the new clips`）
- 目的：使用者新增 5 段附人工腳本的素材（含 2 段正常位），要求測試後再決定方向問題的做法。
- 修改：只更新文件（PLAN 測試紀錄、README 驗證表與已知問題），主程式未修改。`vaild/` 已由使用者改名（加上體位），影片不提交。
- 驗證：一般模式 F1 / 相關：B02 0.59 / 0.214、B03 0.41 / 0.255、F01 0.29 / 0.212、E02 0.60 / 0.082、D02 0.47 / 0.036（hybrid：B02 0.85 / 0.693，其餘相近）。B03、D02 大多數鏡頭方向相反，E02 一半。離線評估「AI 量陰莖露出長度＋整支影片投票」：翻轉 B03、E02，舊 8 段不受影響，有效鏡頭方向正確 70/102 → 81/102。`uv run pytest` 110 個通過、2 個略過。

## 2026-10-29 — 診斷：O01 高低相反（commit: `Record why O01 comes out inverted`）
- 目的：使用者新增 `vaild/O01.mp4`，回報生成的腳本高低完全相反。
- 修改：只更新文件（PLAN 診斷紀錄、README 已知問題），主程式未修改。
- 驗證：以使用者設定（hybrid）重跑：1 個鏡頭、沒有 AI 陰莖方向、符號餘裕 0.84。光流中位數與行程相關 +0.88（是女方身體而不是背景），扣掉後是畫面下緣相對女方往上＝插入，推測是第一人稱正常位、男方主動，「往上＝高」不成立。同樣的耦合在驗證素材的正確鏡頭也常見（A02、D01、E01），不能用來判斷；8B 的體位回答前後矛盾。沒有人工腳本，未計分。`uv run pytest` 110 個通過、2 個略過。

## 2026-10-29 — Hybrid 模式也對齊長鏡頭分段的方向（commit: `Align chunk signs in hybrid focus too`）
- 目的：使用者再次回報行程高低有時相反。使用者用的是 hybrid 模式，而 `align_chunks` 只處理一般模式，hybrid 下 A04 第 8 段相關 −0.86。
- 修改：`pipeline.py` 的 `_scene_signal` hybrid 分支改用 `FlowTracker.component()`，記錄主成分型態、符號餘裕與位置（有用到生殖器區域時取它的，否則取一般區域的；AI 給了陰莖方向時不記錄），讓 `align_chunks` 也能對齊 hybrid 鏡頭。`tests/test_chunks.py` 新增 2 個測試（hybrid 分段會對齊；有 AI 方向時不翻轉）。README 功能表、參數表、驗證表、已知問題同步更新；PLAN 記錄另外兩種方向判斷的離線評估（兩人距離、AI 量陰莖露出長度），都不採用。
- 驗證：`uv run pytest` 110 個通過、2 個略過。8 段素材 `--focus hybrid`（8B、AI 快取），修正前 → 後：A04 F1 0.68 → 0.78、相關 0.046 → 0.261，其餘 7 段完全相同（A02 0.99 / 0.976、B01 0.99 / 0.912、C01 0.98 / 0.868、D01 0.84 / 0.352、E01 0.85 / 0.507、A03 0.85 / 0.498、A01 0.79 / 0.360）；8 段平均 0.871 / 0.565 → 0.884 / 0.592。一般模式的程式未改，分數與上一版相同（0.885 / 0.592）。

## 2026-10-29 — 停用兩個未成年略過備註的測試（commit: `Skip the two apparent-minor note tests`）
- 目的：使用者要求停用。commit `pipeline18off` 把略過備註改為「繼續」，這兩個測試仍檢查「未成年」字樣而失敗。
- 修改：`tests/test_focus.py::test_apparent_minor_skips_scene`、`tests/test_range.py::test_apparent_minor_skips_the_scene` 加上 `pytest.mark.skip`。這兩個測試同時檢查 `skip` 為 True，停用後這部分也不再被測試。
- 驗證：`uv run pytest` 108 個通過、2 個略過。

## 2026-10-29 — 評估：由 AI 決定單一鏡頭的行程方向（commit: `Record that AI cannot tell the stroke direction`）
- 目的：使用者要求讓 AI 判斷體位與誰在動，解決剪接後單一鏡頭高低相反的問題。
- 修改：只更新文件（PLAN.md 新增評估紀錄、README.md 已知問題補充），主程式未修改。離線實驗了兩種方法：成對比較高點／低點畫面的插入深度；請 AI 回答體位、誰在動與陰莖方向，再決定方向。
- 驗證：8B、8 段素材、71 個鏡頭。深度比較逐組正確率 49%／58%，鏡頭判斷 22/53、30/53；體位＋誰在動＋方向的方向一致率 11/24（現行規則 24/24），平均相關 0.612 → 0.307。現行規則猜錯的 5 個鏡頭，AI 都回答看不出。不採用。`uv run pytest` 108 個通過、2 個失敗（失敗的是兩個未成年略過測試，原因是 commit `pipeline18off` 把略過備註改為「繼續」，測試仍檢查「未成年」字樣）。

## 2026-10-29 — 長鏡頭分段的行程方向對齊（commit: `Align the stroke sign across chunks of a long shot`）
- 目的：使用者回報行程高低有時相反（插入時應該越來越低、拔出時越來越高）。原因是一般模式沒有 AI 給的陰莖方向，光流主成分的正負號用「往上動＝位置變高」判斷；動作接近水平或兩人上下相反時，往上與往下幾乎抵銷，符號由雜訊決定。長鏡頭每 20 秒切一段，每段各自判斷，所以同一個鏡頭可能某一段反相。
- 修改：`video/scenes.py` 的 `Scene` 新增 `continued`（因長度切段、非剪接）；`tracking/flow.py` 新增 `FlowTracker.component()`，回傳速度、主成分在整個格網上的空間型態與符號餘裕（0–1），`velocity("auto")` 改為呼叫它；`pipeline.py` 的 `PipelineOptions` 新增 `chunk_align`（開啟）、`chunk_align_similarity`（0.3），`ScenePlan` 記錄型態、餘裕與積分後的位置，新增 `align_chunks()`：同一鏡頭的連續分段以餘裕最大的一段為準，向外逐段比較型態的餘弦相似度，≤ −0.3 就翻轉該段並重新分析，備註寫出翻轉與相似度；只作用於一般模式、`auto` 軸、沒有 AI 方向、非 Hybrid 的光流鏡頭。debug JSON 加入 `sign_margin`。CLI `--chunk-align/--no-chunk-align`；Web UI「長鏡頭分段方向一致」核取方塊，納入記住的設定。新增 `tests/test_chunks.py`（5 個測試）。
- 驗證：`uv run pytest` 108 個通過、2 個失敗；失敗的是 `test_focus.py::test_apparent_minor_skips_scene` 與 `test_range.py::test_apparent_minor_skips_the_scene`，原因是工作區中未提交的 `pipeline.py` 修改（未成年略過的備註改為「繼續」），與本次修改無關，未納入本 commit。8 段素材（8B、AI 快取）關閉 → 開啟：只有 A04 改變，第 11 段（99.9–113.4s）相關 −0.35 → +0.35，整段 F1 0.77 不變、相關 0.193 → 0.219；其餘 7 段分數完全相同。8 段平均 F1 0.885、相關 0.589 → 0.592。

## 2026-10-29 — 陰莖不完整時改為提高最小值（commit: `Raise the floor instead of capping when only the glans is seen`）
- 目的：使用者指定「看得到龜頭、但陰莖不完整」時最大值維持 100，改為把最小值設為 20。
- 修改：`pipeline.py` 的 `PipelineOptions` 新增 `range_floor`（20）、`ScenePlan` 新增 `range_min`；`_apply_range` 分三種情況（看不到龜頭 → 最大值 80；看得到龜頭但不完整 → 最小值 20；完整 → 不限制）；`cap_range` 改名為 `clip_range`，同時截上下限。CLI `--range-floor`；Web UI 新增滑桿並納入記住的設定；debug JSON 加入 `range_min`。`tests/test_range.py` 改寫 1 個、新增 2 個測試。
- 驗證：`uv run pytest` 105 個通過。只有 E01（1 個鏡頭）、A01（5 個鏡頭）的 AI 回答屬於這種情況，重跑這兩段：E01 0.83 / 0.493 不變，A01 0.80 / 0.397 → 0.394（其中 3 個鏡頭人工腳本的低點是 0）；8 段平均 0.885 / 0.589。

## 2026-10-29 — 行程範圍辨識（commit: `Cap scenes where the AI cannot see the whole penis`）
- 目的：使用者要求新增「行程範圍辨識」選項，預設開啟：以每個鏡頭為一組，由 AI 判斷能否完整辨識男性生殖器與其頭部，決定該鏡頭動作的最大值；找不到頭部時最大值設為 80。
- 修改：`ai/prompts.py` 新增 `RangeAnalysis`、`RANGE_PROMPT`；`pipeline.py` 的 `PipelineOptions` 新增 `stroke_range`（開啟）、`range_cap`（80），`ScenePlan` 新增 `range_max`、`range_analysis`，新增 `_detect_ranges`（每鏡頭一次 AI 呼叫）、`_apply_range`（可能有未成年人 → 略過；不完整或看不到龜頭 → 上限 80；呼叫失敗 → 不限制）、`cap_range`（在反轉之後、限速之前把超過上限的位置截到上限）；`report.py` 的 debug JSON 加入 `range_max`、`range_analysis`。CLI `--stroke-range/--no-stroke-range`、`--range-cap`；Web UI「AI 分析」區的核取方塊與滑桿，納入記住的設定。新增 `tests/conftest.py`（測試中不呼叫真正的 AI）、`tests/test_range.py`（10 個測試）。
- 驗證：`uv run pytest` 103 個通過。8 段素材（8B）同一次執行比較不限制 / 等比例縮放 / 截斷，平均 F1 0.885 / 0.885 / 0.885、相關 0.573 / 0.565 / 0.589，採用截斷；主程式重跑 A02（0.99 / 0.966）、D01（0.86 / 0.371）與離線結果一致。94 個鏡頭有 89 個被限制，人工腳本峰值與 AI 判斷無關，見 README「已知問題」。

## 2026-10-28 — 保留停頓與長行程補點（commit: `Add optional dwell and curve points to the output`）
- 目的：使用者指出訊號在底部有短暫停頓，但輸出只有一個轉折點，被簡化成 V 字形；另外希望峰谷間隔較長時能多輸出點。兩者都要可以設定，預設關閉。
- 修改：`signal/process.py` 的 `SignalParams` 新增 `dwell`、`dwell_tol`（0.05）、`dwell_min_ms`（200）、`curve`、`curve_after_ms`（600）、`curve_tol`（5）；新增 `dwell_span`、`_simplify`（Douglas-Peucker）、`shape_points`，`to_actions` 在高頻縮小幅度之後、限速之前加點。CLI `--dwell/--no-dwell`、`--dwell-tol`、`--dwell-min-ms`、`--curve/--no-curve`、`--curve-after-ms`、`--curve-tol`；Web UI「輸出」區兩個核取方塊，勾選後才顯示參數滑桿，並納入記住的設定。`tests/test_signal.py` 新增 4 個、`tests/test_webui.py` 新增 1 個測試。
- 驗證：`uv run pytest` 93 個通過。8 段素材（8B）每段跑一次 pipeline、對同一份訊號套用四種設定（預設輸出與主程式逐點相同），平均 F1 / 相關：預設 0.886 / 0.573、`--dwell` 0.882 / 0.587、`--curve` 0.889 / 0.614、兩者 0.885 / 0.617。三段短片不變；A03 相關 0.52 → 0.68（兩者）、D01 0.31 → 0.41。`--dwell` 的 F1 下降來自評分把兩個同位置的停頓點算成兩個轉折點（A04 0.78 → 0.76、A01 0.80 → 0.79）。預設關閉，預設輸出不變。

## 2026-10-28 — 預覽移到輸出上方（commit: `Move the generate-tab preview above the output file`）
- 目的：使用者要求「產生」分頁的預覽移到「輸出 funscript」上方。
- 修改：`webui.py` 把預覽標題與播放器從頁面下方移到右欄最上方；README 使用方式、PLAN 進度同步更新。
- 驗證：`uv run pytest` 88 個通過，`build()` 可正常建立介面。只調整版面，沒有改偵測、訊號或輸出邏輯，未重跑 `vaild/` 素材。

## 2026-10-28 — 工作規則併入 CLAUDE.md（commit: `Merge AGENTS.md into CLAUDE.md and record pending plan notes`）
- 目的：使用者把工作規則從 `AGENTS.md` 搬到 `CLAUDE.md`，並要求提交工作目錄中所有未提交的修改。
- 修改：刪除 `AGENTS.md`，內容移到 `CLAUDE.md`；README、CHANGELOG 中指向 `AGENTS.md` 的連結改為 `CLAUDE.md`；`PLAN.md` 補上先前未提交的進度紀錄（接觸點提示詞、候選區域選擇評估與實作、高頻縮小幅度、Web UI 記住設定）；`.gitignore` 加入 `CLAUDE.md`、`PLAN.md`（兩者仍被追蹤，忽略規則只對未追蹤的檔案有效）。
- 驗證：沒有改程式；`uv run pytest` 88 個通過。

## 2026-10-28 — Web UI 記住上次使用的設定（commit: `Remember the last-used generate settings in the web UI`）
- 目的：使用者要求 Web UI 記錄上次使用時的設定，不必每次重新調整。
- 修改：`webui.py` 新增 `load_last_form`、`save_last_form`、`restore_form`、`valid_form_value`；按「產生 funscript」時把「產生」分頁的 24 項設定（不含上傳的影片與參考腳本）存到 `.webui-last.json`，開啟頁面時載回；已不存在的選項、超出範圍的數值或型別不符的值會略過、維持預設值。新增「還原預設設定」按鈕（回到預設值並刪除紀錄）。CLI `webui --last-file`；`.gitignore` 加入 `.webui-last.json`；`tests/test_webui.py` 新增 3 個測試。
- 驗證：`uv run pytest` 88 個通過。實際啟動 Web UI，透過 API 送出一組非預設設定後重新載入，24 項全部還原。沒有改偵測、訊號或輸出邏輯，未重跑 `vaild/` 素材。

## 2026-10-28 — 高頻縮小幅度（commit: `Shrink stroke length above a frequency threshold`）
- 目的：動作頻率超過門檻後，頻率越快行程越短，避免高速時仍走滿行程。
- 修改：`signal/process.py` 的 `SignalParams` 新增 `freq_limit_hz`（1.5）、`freq_max_hz`（2.0）、`freq_min_scale`（0.5），新增 `frequency_scale`、`limit_frequency`：每個動作點用與前後點的間隔估計頻率（超過 `hold_after_ms` 的停頓不算），門檻到最高頻率之間線性縮小，以原行程範圍的中心點（該點與前後點平均的中點）為準；`to_actions` 在限速前套用，`pipeline.audio_assisted_actions` 對聲音輔助產生的動作也套用。CLI `--freq-limit`、`--freq-max`、`--freq-min-scale`，Web UI「輸出」區三個滑桿；`tests/test_signal.py` 新增 5 個測試。
- 驗證：`uv run pytest` 85 個通過。8 段素材（8B，F1 / 相關，`--freq-limit 0` → 預設）：A02 0.99 / 0.98 → 0.99 / 0.96、B01 0.99 / 0.94 → 0.99 / 0.91、C01 0.98 / 0.89 → 0.98 / 0.86、D01 0.86 / 0.50 → 0.86 / 0.31、A04 0.78 / 0.22 → 0.78 / 0.18、E01 0.83 / 0.50 → 0.83 / 0.46、A03 0.87 / 0.54 → 0.86 / 0.52、A01 0.80 / 0.43 → 0.80 / 0.40。平均 F1 0.888 → 0.886、相關 0.625 → 0.573。`--freq-limit 0` 與上一版分數相同。相關下降是因為人工腳本在 1.5–2.5 Hz 多半仍接近滿行程，只有 3 Hz 以上才變短。

## 2026-10-28 — 候選區域再確認（commit: `Let the VLM pick the flow region among numbered candidates`）
- 目的：離線評估顯示請 VLM 從編號候選區域中選，再以週期性把關，能改善長片的分析區域。
- 修改：新增 `ai/regions.py`（候選區域：AI 區域、兩人框、聯集、整個畫面、3×3 格子；編號 2×2 裁切拼圖）；`ai/prompts.py` 新增 `RegionPick`、`REGION_PROMPT`；`pipeline.py` 新增 `region_pick`（預設開啟）、`region_pick_margin`，`plan_scenes` 對一般模式的光流鏡頭多呼叫一次 VLM，`_scene_signal` 在選到的區域週期性 > 0 且不低於原區域時換用，並寫進鏡頭備註；`report.py` debug JSON 加上 `pick`；CLI `--region-pick/--no-region-pick`、Web UI 核取方塊；`tests/test_regions.py`。
- 驗證：`uv run pytest` 80 個通過。8 段素材（8B）平均 F1 0.874 → 0.886、相關 0.605 → 0.625；A04 0.68 → 0.78、D01 0.84 → 0.86、A03 0.86 → 0.87、A01 0.79 → 0.80，**E01 0.85 → 0.83**（第 1 鏡頭換成人物框，週期性較高但內容不對，0.77 → 0.35），短片三段不變。

## 2026-10-28 — 評估請 VLM 從編號候選區域中選擇（commit: `Evaluate letting the VLM pick among numbered regions`）
- 目的：上一項評估顯示好的分析區域存在（上限 0.907），但只看週期性選不到；改試讓 VLM 從編號候選中選。
- 修改：沒有改程式（實驗腳本在 scratchpad）。
- 驗證：8B，沿用上一項的候選訊號。把每個候選的 4 張關鍵幀裁切拼成 2×2 小圖讓 VLM 選，並在選的區域週期性不低於 AI 區域時才換：平均 F1 0.874 → 0.890、相關 0.611 → 0.633，沒有任何一段 F1 下降（A04 0.69 → 0.78、D01 0.84 → 0.86、A01 0.79 → 0.80）。直接用 VLM 的選擇（沒有保護）0.879；在第一幀畫編號框 0.863。門檻是在同樣素材上挑的，30B 未測；是否實作主程式待決定。

## 2026-10-28 — 評估依訊號品質選擇分析區域（commit: `Evaluate picking the flow region by signal quality`）
- 目的：評估「不只相信 AI 的一個框，對多個候選區域算訊號、依週期性選擇」是否值得實作。
- 修改：沒有改程式；README「已知問題」補上結論。
- 驗證：候選 = AI 區域、兩人框、聯集、整個畫面、3×3 格子。上限（以人工腳本挑選）8B 0.874 → 0.907、30B 0.659 → 0.906；實際規則 8B 最好 0.876（等於沒變）、30B 最好 0.738，A02 仍是 0.02。週期性指標分不出「節奏對但相位差」的錯誤區域，不採用。

## 2026-10-28 — 撤銷接觸點提示詞（commit: `Revert the contact-area focus_roi prompt`）
- 目的：`Ask for a tight contact-area focus_roi in the scene prompt` 讓預設模型 8B 退步（平均 F1 0.874 → 0.863、相關 0.605 → 0.532）。
- 修改：`ai/prompts.py`、`tests/test_ai.py` 還原到該 commit 之前；README 移除 30B 新提示詞的驗證表，改寫已知問題。
- 驗證：`uv run pytest` 69 passed。8B：A02 0.99 / 0.98、B01 0.99 / 0.94、C01 0.98 / 0.89、D01 0.84 / 0.47、A04 0.68 / 0.07、E01 0.85 / 0.51、A03 0.86 / 0.55、A01 0.79 / 0.44，與修改前完全相同。

## 2026-10-28 — 新提示詞在 8B 上的回歸測試（commit: `Record 8B regression from the contact-area prompt`）
- 目的：伺服器改回 Qwen3-VL-8B，確認上一條的提示詞修改有沒有讓 8B 退步。
- 修改：沒有改程式；README「已知問題」與 PLAN 記錄結果。
- 驗證：8B（舊提示詞 → 新提示詞）平均 F1 0.874 → 0.863、平均相關 0.605 → 0.532；B01 相關 0.94 → 0.46、A03 F1 0.86 → 0.79。原因：8B 有 22/59 個互動鏡頭不給區域。另一種寫法（v2）平均 F1 0.818，更差，未採用。

## 2026-10-28 — 一般模式的分析區域改為框接觸點（commit: `Ask for a tight contact-area focus_roi in the scene prompt`）
- 目的：30B 把 `focus_roi` 理解成「在動的那個人」，常照抄人物框，區域太大造成退步。
- 修改：
  - `ai/prompts.py`：`SCENE_PROMPT` 要求 `focus_roi` 只框 `ref_a` 與 `ref_b` 接觸的地方、不要照抄人物框；`SceneAnalysis` 把 `focus_roi` 移到 `ref_a`/`ref_b` 之後。
  - `tests/test_ai.py`：檢查欄位順序與提示詞內容。
  - README：新增 30B 驗證表與已知問題。
- 驗證：`uv run pytest` 70 passed。30B（F1 / 相關）：A02 0.99 / 0.97、B01 0.99 / 0.90、C01 0.98 / 0.90、D01 0.86 / 0.46、A04 0.75 / 0.25、E01 0.82 / 0.37、A03 0.86 / 0.55、A01 0.70 / 0.31；平均 F1 0.658 → 0.869（8B 舊提示詞 0.874）。區域放大 25% / 50% 試過不採用。8B 用新提示詞未驗證。

## 2026-10-28 — 查明 30B 退步原因（commit: `Record why Qwen3-VL-30B-A3B scores lower`）
- 目的：使用者問為什麼換模型反而更差。
- 修改：沒有改程式；PLAN 補上原因：30B 的 `focus_roi` 常照抄人物框（A01 21 個中 12 個，8B 18 個中 3 個），平均面積 46%（8B 20%）。
- 驗證：沒有改程式，分數同上一條。

## 2026-10-28 — 評估 Qwen3-VL-30B-A3B（commit: `Evaluate Qwen3-VL-30B-A3B on the validation set`）
- 目的：使用者把 vLLM 模型換成 `QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ`，測試效果。
- 修改：沒有改程式。PLAN 新增評估紀錄；README「已知問題」新增 30B 的結果。
- 驗證：`uv run pytest` 69 passed。8 段素材（F1 / 相關，8B → 30B）：A02 0.99 / 0.98 → 0.02 / 0.91、B01 0.99 / 0.94 → 0.99 / 0.88、C01 0.98 / 0.89 → 0.37 / 0.91、D01 0.84 / 0.47 → 0.84 / 0.53、A04 0.68 / 0.07 → 0.69 / 0.18、E01 0.85 / 0.51 → 0.81 / 0.43、A03 0.86 / 0.55 → 0.86 / 0.55、A01 0.79 / 0.44 → 0.68 / 0.19。平均 F1 0.874 → 0.658。原因是 30B 的分析區域太鬆（接近整個畫面或貼著下緣）。

## 2026-10-28 — 光流節奏濾波、每鏡頭幅度基準（commit: `Band-pass flow signals around their own tempo`）
- 目的：長片的低分鏡頭多是漏點；分析後發現動作其實在光流訊號中，只是被漂移和其他頻率的晃動蓋住。
- 修改：
  - `signal/process.py`：新增 `dominant_tempo`、`rhythm_filter`（頻譜集中在單一節奏時做帶通濾波）、`scene_scale`（每個鏡頭的滿行程基準往自己的幅度靠近一半）；`SignalParams` 新增 `rhythm_*`、`scene_scale_blend`；`ProcessedSignal` 記錄 `tempo_hz`。
  - `pipeline.py`：光流套用節奏濾波（骨架不套用）；每個鏡頭用 `scene_scale`；AI 沒給互動區域時改用兩人框的聯集。
  - `cli.py`、`webui.py`：新增 `--rhythm-filter/--no-rhythm-filter` 與「節奏濾波（光流）」選項；鏡頭表與 debug JSON 顯示濾波的節奏。
  - `tests/`：節奏濾波（找回被漂移蓋住的動作、不把雜訊與大漂移當節奏）、`scene_scale`、兩人框聯集的測試。
  - README、PLAN、AGENTS：更新驗證結果與已知問題；合成影片回歸測試改用 `--mode pose`。
  - **更正前一次修改（`Use optical flow for every scene in auto mode`）的紀錄**：合成影片的分數讀錯了輸出順序，實際上自動模式改成光流後，合成影片 F1 從 0.97 變成 0.00（光流追不到沒有紋理的火柴人），「不用 AI 的骨架模式輸出 0 個點」也是錯的。
- 驗證：`uv run pytest` 69 項通過。F1 / 相關係數（前 → 後）：A02 0.99 / 0.94 → 0.99 / 0.98、B01 0.99 / 0.74 → 0.99 / 0.94、C01 0.98 / 0.86 → 0.98 / 0.89、D01 0.80 / 0.38 → 0.84 / 0.47、A04 0.68 / 0.07 → 0.68 / 0.07、E01 0.85 / 0.47 → 0.85 / 0.51、A03 0.86 / 0.51 → 0.86 / 0.55、A01 0.79 / 0.41 → 0.79 / 0.44。合成影片（`--mode pose`）0.97 / 0.94；合成前後移動影片 0.58 / 0.57、加聲音輔助 0.88 / 0.78。

## 2026-10-28 — 自動模式改為一律光流（commit: `Use optical flow for every scene in auto mode`）
- 目的：逐鏡頭比較後，舊自動模式選用骨架的 9 個鏡頭中有 7 個不如光流，而且多半差很多，是長片失分主因之一。
- 修改：
  - `pipeline.py`：`auto` 一律用光流，移除 `_pose_viable`；只有 `--mode pose` 才載入 YOLO 模型；`plan_scenes` 不再需要 `pose` 參數。
  - `cli.py`、`webui.py`：模式說明改為「自動（光流）」。
  - `tests/test_focus.py`：新增自動模式選用光流的測試。
  - README、PLAN：更新驗證結果、已知問題，記錄靜止鏡頭判定的評估（現有特徵分不出靜止，完美去除的上限也只有 F1 +0.01–0.04，因此沒有改主程式）。
  - 一併提交 `vaild/` 中兩個舊檔名腳本的刪除（已改名為 A01、A02，且整個 `vaild/` 已不納入版本控制）。
- 驗證：`uv run pytest` 64 項通過。自動模式 F1 / 相關係數：A02 0.99 / 0.94、B01 0.99 / 0.74、C01 0.98 / 0.86（不變）；D01 0.67 → 0.80 / 0.18 → 0.38、A04 0.67 → 0.68 / 0.07、E01 0.81 → 0.85 / 0.38 → 0.47、A03 0.82 → 0.86 / 0.46 → 0.51、A01 0.78 → 0.79 / 0.41。合成影片 F1 0.97 不變，相關 0.93 → 0.90（**此句有誤，見上方 `Band-pass flow signals around their own tempo` 條目的更正**）。

## 2026-10-28 — 整個 vaild/ 不納入版本控制（commit: `Ignore the whole vaild directory`）
- 目的：驗證素材（影片與人工腳本）都只留在本機。
- 修改：`.gitignore` 由只忽略 `vaild/` 中的影片檔，改為忽略整個 `vaild/`。
- 驗證：無程式修改。

## 2026-10-28 — 以 8 段新驗證素材重新評分（commit: `Validate on expanded vaild set`）
- 目的：`vaild/` 新增多段附人工腳本的素材，確認目前版本在更多素材上的表現。
- 修改：README 驗證結果表與已知問題、PLAN、AGENTS.md 與 `signal/audio.py` 註解改用新名稱。程式邏輯沒有改動。
- 驗證：`uv run pytest` 61 項通過。自動模式 F1 / 相關係數：A02 0.99 / 0.94、B01 0.99 / 0.74、C01 0.98 / 0.86、D01 0.67 / 0.18、A04 0.67 / 0.07、E01 0.81 / 0.38、A03 0.82 / 0.46、A01 0.78 / 0.41（A01、A02 與上次相同）。強制光流時長片 F1 提高 0.01–0.13（D01 0.80、E01 0.85、A03 0.86）。

## 2026-10-28 — 輸出列表移到「輸出」分頁（commit: `Move output list to its own tab`）
- 目的：輸出列表獨立成分頁，點擊檔名就能下載，並新增全部清除按鈕。
- 修改：
  - `webui.py`：
    - 新增「輸出」分頁：以 HTML 表格列出檔案，檔名是下載連結（Gradio `/gradio_api/file=` 路由，需要登入、只限輸出目錄；檔名經跳脫）。
    - 「全部清除」按鈕需要再按「確定全部清除」才會執行；切換到分頁時更新列表。
    - 「設定」分頁只保留保留天數、儲存與「立即刪除過期的輸出」，移除原本的列表、下載欄與「刪除全部」勾選。
    - 移除 `pick_output`，`delete_outputs` 拆成 `delete_expired` / `clear_outputs`。
  - `tests/test_webui.py`：改寫刪除測試；新增下載連結測試（實際經由 app 下載回傳 200、輸出目錄以外 403、啟用登入時未登入 401、檔名跳脫）。
  - README、PLAN 更新。
- 驗證：`uv run pytest` 61 項全部通過。以暫存輸出目錄啟動 Web UI，確認頁面設定中有「輸出」分頁、列表與清除按鈕。實際瀏覽器點擊未驗證。

## 2026-10-28 — Web UI 瀏覽並重新下載輸出（commit: `List web UI outputs for download`）
- 目的：在「輸出檔案」區塊查看還沒刪除的檔案，並能再次下載。
- 修改：
  - `outputs.py`：`OutputStore.files()`（新的在前）、`find()`（只回傳列表中的檔案，拒絕 `../` 等路徑）。
  - `webui.py`：「輸出檔案」新增檔案列表（資料夾、檔名、大小、修改時間）與下載欄，點一列即可下載；產生、刪除、儲存設定、重新整理後更新列表。
  - 測試：`tests/test_outputs.py`、`tests/test_webui.py` 新增列表與下載測試。
  - README、PLAN 更新。
- 驗證：`uv run pytest` 61 項全部通過。以暫存輸出目錄啟動 Web UI：列表顯示檔案；輸出目錄中的檔案經 Gradio 檔案網址下載回傳 200，輸出目錄以外的檔案回傳 403。點擊列表的實際瀏覽器操作未驗證。

## 2026-10-28 — Web UI 定期或手動刪除輸出（commit: `Add web UI output cleanup`）
- 目的：`out/webui/` 的輸出會一直累積，需要能在 Web UI 設定自動刪除或手動刪除。
- 修改：
  - 新增 `outputs.py`：`OutputStore`，計算輸出數量與大小、保留天數（`.webui-cleanup.json`）、依年齡或全部刪除、背景每小時清理。只刪除 `YYYYMMDD-HHMMSS` 形式的資料夾。
  - `webui.py`：「設定」分頁新增「輸出檔案」（目前用量、保留天數、儲存、立即刪除、刪除全部確認、重新整理）；每次產生完成後清理過期輸出；`launch` 啟動背景清理；`create_app` / `launch` 新增 `cleanup_file`。
  - `cli.py`：`webui --cleanup-file`；新增 `clean-webui` 指令（`--older-than-days`、`--all`、`--retention-days`）。
  - `.gitignore` 加入 `.webui-cleanup.json`；README、PLAN 更新。
  - 新增 `tests/test_outputs.py`，`tests/test_webui.py` 加入刪除測試。
- 驗證：`uv run pytest` 59 項全部通過。以暫存輸出目錄啟動 Web UI：設定分頁出現「輸出檔案」區塊，啟動時刪除了過期的資料夾、保留未過期的。不影響偵測與輸出內容，未重跑驗證素材。

## 2026-10-28 — Web UI 輸出檔名與影片相同（commit: `Keep video name for web UI output`）
- 目的：Web UI 會把影片檔名中的空白、括號等字元換成底線，導致腳本與影片名稱不同，播放器無法自動載入。
- 修改：
  - `webui.py`：新增 `output_stem()`，只替換 Windows／Unix 檔名不允許的字元（`<>:"/\|?*` 與控制字元），保留空白與其他字元；長度上限 150，去掉頭尾的空白與句點。
  - 新增 `tests/test_webui.py`。
  - README、PLAN 同步說明。
- 驗證：`uv run pytest` 52 項全部通過。只改檔名，不影響偵測與輸出內容，未重跑驗證素材。

## 2026-10-27 — 登入帳號改在 Web UI 設定（commit: `Manage web UI login in the settings tab`）
- 目的：帳號密碼不寫在 `start-webui.sh`，改在 Web UI 設定；啟用登入但尚未設定時，預設為 `user` / `password`。
- 修改：
  - 新增 `auth.py`：`Credentials`。檔案只存加鹽 scrypt 雜湊，權限 600；尚未設定時預設 `user` / `password`；新密碼至少 8 個字元，且不能是預設密碼。
  - `webui.py`：
    - 「設定」分頁新增「登入帳號」，修改時需要目前的密碼。
    - 使用預設帳號密碼時，頁面頂端顯示提醒。
    - 登入檢查改用函式，修改後立即生效。
    - `create_app` / `launch` 改為 `auth_enabled` / `auth_file`。
  - `cli.py`：`webui --auth/--no-auth`（環境變數 `FUNSCRIPT_GEN_AUTH_ENABLED`）、`--auth-file`；移除以 `帳號:密碼` 傳入的方式。
  - `start-webui.sh`：`WEBUI_AUTH` 改為 `WEBUI_AUTH_ENABLED`（yes / no）。
  - `.gitignore` 加入 `.webui-auth.json`；README 更新。
  - 新增 `tests/test_auth.py`。
- 驗證：
  - `uv run pytest` 50 項通過。
  - 透過 `start-webui.sh` 實測：
    - 無效設定被拒絕。
    - 啟動時顯示預設帳號提醒；預設帳號登入回傳 200，錯誤密碼回傳 400。
    - 在 Web UI 修改後，舊帳號登入回傳 400，新帳號回傳 200，不需重新啟動。
    - 檔案中沒有明文密碼，權限 600，git 忽略。

## 2026-10-27 — 安裝與啟動腳本（commit: `Add set-env.sh and start-webui.sh`）
- 目的：自動安裝設定環境，並集中設定、啟動 Web UI 伺服器。
- 修改：
  - 新增 `set-env.sh`：確認／安裝 uv（互動詢問，`-y` 自動）、`uv sync --frozen` 安裝 Python 3.12 與套件、下載 YOLO 權重、建立 `.env`（互動輸入連線資訊，權限 600）、測試 AI 連線、`--test` 執行測試。
  - 新增 `start-webui.sh`：伺服器設定（位址、連接埠、登入、輸出目錄）；優先順序為環境變數 > `start-webui.local.sh` > 預設值；開放區網但未設登入時拒絕啟動；檢查連接埠占用；密碼經由環境變數傳給伺服器。
  - `cli.py`：`webui --auth` 可從 `FUNSCRIPT_GEN_AUTH` 讀取，新增 `--output-dir`（`FUNSCRIPT_GEN_OUTPUT_DIR`）。
  - `.gitignore` 加入 `start-webui.local.sh`；README 更新安裝與啟動說明。
- 驗證：
  - 在現有專案與全新 clone 中執行 `set-env.sh -y --test`：全新 clone 約 29 秒完成（uv 快取已存在），43 項測試通過。
  - 互動模式正確寫入 `.env`。
  - `start-webui.sh`：
    - 錯誤設定被拒絕：開放區網未設登入、登入格式錯誤、連接埠超出範圍、連接埠被占用。
    - 登入正確時回傳 200，錯誤時 400；未登入存取 API 回傳 401。
    - 伺服器程序的指令參數中沒有密碼。
    - 自訂輸出目錄會建立；設定的優先順序正確。

## 2026-10-27 — 聲音判定輔助改為音訊引導（commit: `Guide picture signal with audio tempo for depth motion`）
- 目的：處理朝向鏡頭前後移動、畫面變化不明顯但聽得出節奏的片段。
- 修改：
  - `signal/audio.py` 改寫：`periodicity()` 只認真正的自相關峰值（修正錯誤）；新增 `assist_window()`（觸發條件：畫面沒有節奏／動作很小／節奏與聲音不一致；用聲音節奏帶通過濾畫面訊號，與聲音相關 ≥ 0.5 才替換）、`reference_amplitude()`、`guided_actions()`。
  - `pipeline.py`：依模式計算全片典型幅度，改用新的逐視窗判斷。
  - `report.py`：除錯資料加入 `audio_spans`；Web UI 說明文字更新。
  - 新增 `scripts/make_synthetic_depth.py`；`tests/test_audio.py` 改寫（小動作恢復、靜止 + 音樂不產生動作、清楚畫面不被替換等）。
- 驗證：`uv run pytest` 43 項通過。合成前後移動影片：F1 0.58 → 0.88、相關係數 0.50 → 0.68（前後段 0.35 → 0.85，上下段不變，靜止 + 音樂段 0 個動作）。`A01`（一般模式 + 聲音輔助）：F1 0.78 不變。
- 備註：使用者提供的 `vaild/hsmtsisi_g.mp4` 在獨立檢查中，有部分畫面被判斷可能有未成年人，因此沒有用這段素材分析或調整參數。

## 2026-10-27 — 聲音判定輔助（實驗性）（commit: `Add experimental audio assist`）
- 目的：在畫面看不出節奏時，用聲音的起伏輔助判定。
- 修改：
  - 新增 `signal/audio.py`：取音訊並計算起點強度（頻譜通量）、週期性、帶通濾波產生位置、找出要替換的視窗、產生動作點。
  - `pipeline.py`：`PipelineOptions.audio_assist`／`audio`；新增 `audio_assisted_actions()`；鏡頭備註顯示聲音輔助的秒數；metadata 記錄是否使用。
  - CLI `--audio-assist`；Web UI「分析目標」下新增「聲音判定輔助加強（實驗性）」勾選框（可與任一分析目標搭配）。
  - 新增 `tests/test_audio.py`（合成點擊音軌）。
- 驗證：`uv run pytest` 41 項通過。`A01`（一般模式）預設門檻下替換 0 秒，F1 0.78 不變；放寬門檻替換 4–12 秒，F1 0.76–0.77。沒有音軌的影片可正常執行。預設關閉。

## 2026-10-27 — 聲音判定輔助的可行性評估（commit: `Record audio-assist feasibility study in PLAN`）
- 目的：評估以聲音起伏輔助判定的可行性，以及是否需要額外模型。
- 修改：只更新 PLAN.md，記錄實測結果；沒有修改程式。
- 驗證：在 `A01` 上，音訊節奏與人工腳本相符的視窗 42%（完全相符 27%）；轉折點對齊聲音起點 46%／42%，隨機基準 39%。

## 2026-10-27 — Hybrid 分析目標（實驗性）（commit: `Add experimental hybrid focus mode`）
- 目的：依陰莖在畫面中是否可辨認、是否被遮擋，逐幀選擇用加強模式或一般模式的區域。
- 修改：
  - `ai/prompts.py`：`FocusAnalysis` 新增 `frames`（每個關鍵幀的 visible／occluded），提示詞同步更新。
  - `tracking/flow.py`：`velocity()` 可指定 `roi`，同一份光流場可讀取多個區域；抽出 `integrate()`。
  - `pipeline.py`：新增 `focus="hybrid"`、`HybridAnalysis`；整理出 `_apply_general` / `_apply_focus` / `_apply_hybrid`；新增 `frame_choice()`（最近關鍵幀的判斷）與 `splice_velocity()`（方向相反時翻轉一般區域後拼接）。
  - CLI `--focus hybrid`、Web UI「分析目標」新增 Hybrid、鏡頭表顯示兩個區域與使用比例。
  - `tests/test_focus.py` 新增 Hybrid、逐幀選擇與拼接的測試。
- 驗證：`uv run pytest` 36 項通過。`A01`：Hybrid F1 0.76 / 相關係數 0.31，加強模式 0.72 / 0.28（新增 `frames` 欄位後重跑），一般模式 0.78 / 0.41。
- 備註：工作目錄中使用者對 `prompts.py` 的未提交修改（未成年人判斷提示詞）在這次修改前先暫存，修改提交後原樣放回，未包含在這個 commit 中。

## 2026-10-27 — Web UI 的 AI 設定與參考腳本開關（commit: `Add AI settings tab and reference-script toggle to web UI`）
- 目的：在 Web UI 中設定 AI API 與選擇模型；參考腳本功能改為可開關、預設關閉。
- 修改：
  - `config.py`：新增 `save_env()`（只改 AI 相關的變數，保留其他行，權限設為 600）、`list_models()`。
  - `pipeline.py`：`PipelineOptions.ai_settings` 可傳入 AI 設定，不再固定讀 `.env`。
  - `webui.py`：新增「設定」分頁（端點、金鑰、模型清單、座標格式、測試連線、儲存）；「進階」新增「啟用參考腳本」開關，關閉時隱藏產生與預覽分頁的參考腳本欄位，並忽略已上傳的參考腳本。
  - 新增 `tests/test_config.py`。
- 驗證：`uv run pytest` 31 項通過。在暫存目錄（使用 `.env` 的副本）啟動伺服器實測：取得模型清單、測試連線、拒絕非 http 網址、儲存後金鑰保留且不回傳到頁面、`.env` 權限 600、參考腳本開關關閉時不評分也不疊加、開啟時兩者都有。偵測邏輯沒有變動。
- 備註：工作目錄中 `src/funscript_gen/ai/prompts.py` 有使用者自行修改的未提交變更（未成年人判斷的提示詞），不包含在這個 commit 中。

## 2026-10-27 — 回復：未成年人判斷的多幀門檻與略過比例（commit: `Revert "Require two flagged frames before skipping and show skip rate"`）
- 目的：使用者要求回復到上一步。
- 修改：以 `git revert f5dbd58` 撤銷上一次修改。未成年人判斷恢復為整段判斷（`apparent_minor`），AI 判斷可能有未成年人就略過該鏡頭；移除略過比例的顯示。README、PLAN 隨之回到上一版。
- 驗證：`uv run pytest` 30 項通過。

## 2026-10-27 — 加強目標判斷選項（實驗性）（commit: `Add experimental genital-focus analysis mode`）
- 目的：讓 AI 專注於男性生殖器與互動部位，以提高目標判斷的準確度。
- 修改：
  - `ai/prompts.py`：新增 `FocusAnalysis` schema 與 `FOCUS_PROMPT`（接觸部位、緊貼的區域、陰莖基部與前端、未成年人判斷）。
  - `tracking/flow.py`：`velocity()` / `signal()` 新增 `direction` 參數，以陰莖方向決定正負號。
  - `pipeline.py`：新增 `focus` 選項；加強模式固定使用光流、區域外擴 20%、可能有未成年人的鏡頭略過。
  - CLI `generate --focus`、`ai-check --focus`（會畫出陰莖方向箭頭）；Web UI 新增「分析目標」選項；鏡頭表顯示略過與接觸部位。
  - 新增 `tests/test_focus.py`、`tests/test_flow.py::test_direction_sets_the_sign`。
- 驗證：`uv run pytest` 30 項通過。`A01`：F1 0.66、相關係數 0.14（一般模式 0.78 / 0.41），比一般模式差，原因是 AI 很少給出區域、從未給出陰莖位置。`A02` 被判斷為可能有未成年人而整段略過。預設維持一般模式。

## 2026-10-27 — Web UI 預覽播放器（commit: `Add OFS-style preview player to web UI`）
- 目的：在 Web UI 中邊看影片邊檢查產生的 funscript，類似 OpenFunscripter。
- 修改：
  - 新增 `src/funscript_gen/preview.py`：自成一體的播放器 HTML，包含影片、即時位置條、捲動時間軸、速度熱度圖與鍵盤操作，以 iframe 嵌入。
  - `webui.py`：產生完成後自動顯示預覽；新增「預覽」分頁；改用自建的 FastAPI app 掛載 Gradio，並新增 `/media/<token>` 路由提供影片（支援 Range）；啟動方式改為 uvicorn。
  - 新增 `tests/test_preview.py`（資料嵌入、跳脫、媒體路由與 Range）。
  - README、PLAN 更新。
- 驗證：`uv run pytest` 26 項通過；播放器 JS 通過 Node 語法檢查與插值邏輯測試；實際啟動伺服器，以驗證素材測試預覽載入與影片 Range 請求（206）。未在瀏覽器中檢查畫面。偵測邏輯沒有變動，不需重跑驗證分數。

## 2026-10-27 — 建立工作規則與版本控制（commit: `Add AGENTS.md rules, changelog and git history`）
- 目的：記錄專案做事的規則，並讓每次修改都能回復。
- 修改：新增 `AGENTS.md`（工作規則）、`CLAUDE.md`（讓 Claude Code 自動載入 AGENTS.md）、`CHANGELOG.md`；初始化 git；`.gitignore` 排除 `vaild/` 中的影片。
- 驗證：`uv run pytest` 23 項通過。
- 備註：這是第一個 commit，包含以下各條目的所有既有程式。以下條目是補記的開發歷程，沒有各自的 commit，無法個別回復。

## 2026-10-27 — 光流改良（補記）
- 目的：第二段驗證素材 `A01` 的 F1 只有 0.54。
- 修改：修正光流訊號被骨架模式的最小幅度門檻誤刪的單位錯誤；光流改用區域內所有格子的主成分分析找出主要動作（`tracking/flow.py`）；新增 `scripts/flow_dump.py`。
- 驗證：`A01` F1 0.54 → 0.78、相關係數 0.18 → 0.41；`A02` F1 0.99、相關係數 0.94。

## 2026-10-27 — 保留幅度模式（補記）
- 目的：小動作被拉成滿行程。
- 修改：新增「保留幅度」（預設）與「填滿行程」兩種模式、行程倍率；CLI `--amplitude`、`--gain`，Web UI 同步。
- 驗證：新增 4 項單元測試；驗證素材分數不變。

## 2026-10-27 — Web UI 與 README（補記）
- 修改：新增 Gradio Web UI（`funscript-gen webui`）、`report.py`、輸出範圍設定、README.md。

## 2026-10-27 — M0–M3（補記）
- 修改：專案骨架、CLI、funscript 讀寫、影片解碼、骨架偵測與追蹤、訊號後處理、vLLM provider、鏡頭切分、光流模式、每段自動選擇模式。
- 驗證：`A02` F1 0.99、相關係數 0.93；合成影片 F1 0.97。
