# funscript-gen 開發者指南

這份文件給參與開發的人：開發環境、測試與驗證、目前的驗證結果、專案結構，以及已知問題的技術細節。使用說明在 [README.zh.md](README.zh.md)（英文版 [README.md](README.md)）。

| 文件 | 內容 |
|---|---|
| [README.md](README.md)（英文）、[README.zh.md](README.zh.md)（繁體中文） | 給使用者：功能、安裝、用法、目前的限制（GitHub 首頁顯示英文版；Docker、Windows 免安裝版的說明也各有英文版） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系統流程圖：各步驟、可選項目、AI／GPU／CPU 的分工 |
| [PLAN.md](PLAN.md) | 目前的架構、待解決的問題、仍有效的決策與限制、已放棄的方案、後續工作、最近的開發紀錄 |
| [docs/archive/PLAN-archive.md](docs/archive/PLAN-archive.md) | 2026-11-08 以前依時間的完整開發紀錄與實驗數字、之前的驗證紀錄 |
| [CHANGELOG.md](CHANGELOG.md) | 每次修改的摘要（對應一個 commit） |
| [LICENSE](LICENSE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | PolyForm Noncommercial 授權條款（禁止商業使用）與第三方套件／模型授權聲明 |

要回復某次修改：`git log --oneline` 找到它，再 `git revert <commit>`（每次修改是一個獨立的 commit，CHANGELOG 記有對應的 commit 標題）。

---

## 開發環境與測試

```bash
uv sync                    # 安裝套件（或 ./set-env.sh）
uv sync --extra pose       # 另外安裝骨架模式的 PyTorch（CPU 版）與 YOLO；裝過之後 uv sync 都要加 --extra pose
uv sync --extra pose-cuda  # 同上，CUDA 版 PyTorch（NVIDIA 顯示卡；和 pose 擇一，不能同時）
uv run pytest              # 單元測試（含 tests/test_synthetic.py：有紋理的合成影片的完整流程，光流模式）
```

- 骨架模式的火柴人合成影片（`scripts/make_synthetic.py`）需要 `--extra pose`。
- **Docker**：`docker/` 有 `Dockerfile`、兩個 compose 檔（只有 funscript-gen；加上 Ollama）與使用說明。映像檔以 `uv sync --frozen --no-dev` 依 `uv.lock` 安裝到 `/opt/venv`，工作目錄與 `HOME` 都是 `/data`（`.env`、`.webui-*.json`、`out/`、`~/.cache` 全部落在這個 volume）；`entrypoint.sh` 第一次啟動時由 `INIT_VLLM_*` 建立 `.env`（不直接用 `VLLM_*` 環境變數，否則會蓋過 Web UI 存進 `.env` 的設定）。改到相依套件、系統套件、檔案寫入位置或 Web UI 的啟動參數時要一併更新 `docker/`（維護者的工作規則）。
- **Windows 免安裝版**：見下面的「Windows 免安裝版的建置」。
- 修改的程式寫法要和周圍一致；新功能附單元測試，修 bug 先寫能重現問題的測試。

### 偵測模型檢視器（`scripts/detect_viewer.py`）

開發者用的測試網頁，**不是主程式的功能**（沒有語言包、不在 `funscript-gen` 指令中、不隨 Windows 免安裝版與 Docker 發布），用來看各個偵測模型在一支影片的某一幀或整支影片上抓到什麼。

```bash
uv run python scripts/detect_viewer.py                      # http://127.0.0.1:7861，只限本機
uv run python scripts/detect_viewer.py --port 7862 --share-lan   # 區網內的其他電腦也能開
```

- 上傳影片後用「Time」滑桿選時間點（放開即偵測），勾選要比較的模型，同一幀會並排顯示各模型的標註圖、框的表格（標籤、信心值、座標）、耗時與使用的運算裝置。
- 模型：DeepGHS 的 `anime_censor_detection`、`anime_person_detection`、`anime_head_detection`、`anime_face_detection` 的所有版本（從 Hugging Face 即時列出，離線時只有少數預設）、NudeNet 320n、以及「VLM scene analysis」（用 `.env` 的 vLLM／Ollama，看從該時間起的 4 張畫面，畫出人物框 A／B 與互動區域，並列出完整 JSON）。
- 信心門檻 0 表示各模型自己建議的門檻（`threshold.json`；沒有則 0.25）。「Whole video」可以平均抽 10–300 張畫面，統計每個模型每種標籤出現在多少比例的畫面（比較召回率用）。
- 沒有密碼：`--share-lan` 只在信任的區網使用；影片暫存在本機的暫存資料夾，只有 VLM 功能會把畫面送到 `.env` 的主機（見 CLAUDE.md 第 5 節）。`rtdetr`、`yv10` 等輸出格式不同的變體可能無法解碼。
- 偵測器沿用 `tracking/parts.py` 的 `PartDetector`（YOLOv8 ONNX 的前處理與框解碼），所以其他同格式的模型只要換模型檔。

### 設計上要知道的事

- **設定只有一個來源**：所有使用者設定定義在 `options.py` 的 `OPTIONS` 表中，CLI 的 `generate`／`render` 參數、Web UI「產生」分頁的表單、記住的設定、設定組（`PRESETS`）與輸出檔 metadata 都由它產生。新增設定只要在表中加一筆，`stage` 標明它屬於分析還是 render 階段。訊號參數集中在 `SignalParams`，AI 設定集中在 `config.Settings`。
- **分析與 render 分開**：`analyze_video`（鏡頭、AI、光流、部位框、聲音；耗時）的結果可以存檔，`render`（訊號 → 方向 → funscript）便宜、可重複。分析設定改變時才要重新分析；Web UI 沿用上次的分析、CLI 的 `render`、驗證執行器的 `--replay` 都靠這個分界。
- **可追溯的輸出**：輸出檔的 metadata（`funscript_gen`）記錄版本、程式碼雜湊、git commit、AI 模型與全部設定（`version.py`）。
- **快取**：AI 回應以請求內容為鍵存在 `~/.cache/funscript-gen/ai/`；部位框以影片路徑、大小與修改時間為鍵存在 `~/.cache/funscript-gen/parts/`。 `funscript-gen cache info` 列出各資料夾的檔案數與大小，`cache clear [ai|parts|poses|all] [--older-than 天數]` 清除（會先詢問，`-y` 略過；只清可以重做的快取，下載的模型不動）。AI 的快取寫入是原子的（先寫暫存檔再換名），讀到壞檔當作沒有快取。
- **檔案位置集中在 `paths.py`**：`.env`、`.webui-*.json` 預設在工作目錄，Web UI 的輸出在 `out/webui/`，快取在 `~/.cache/funscript-gen/`。設了 `FUNSCRIPT_GEN_HOME` 時全部改到該資料夾（`.env`、`out/`、`cache/`、`tmp/`），`funscript_gen/__init__.py` 也把 Hugging Face、Gradio、Matplotlib 的快取導進去（Windows 免安裝版用這個機制）。新增寫入檔案的地方要經過 `paths.py`。
- **多語言**：使用者看得到的文字都在語言包（`src/funscript_gen/lang/*.toml`，`[meta]` 加上 `[texts]` 的 `"key" = "文字"`），程式用 `i18n.t("key", 參數=值)` 取用，`zh-TW.toml` 是原稿、缺的文字退回它。語言包也從外部資料夾讀取（`FUNSCRIPT_GEN_LANG_DIR`，再來是工作目錄的 `lang/`），同代碼的外部檔案取代內建的；語言依序由 `--lang`、`FUNSCRIPT_GEN_LANG`、Web UI 記住的選擇（`.webui-last.json` 的 `lang`）、系統語言、英文決定。Web UI 的元件用 `webui.ui()` 建立並登記（文字以 `Late` 延遲查表），切換語言時一次 `gr.update` 全部更新，不必重新整理；預覽播放器、分析備註在產生當下就定下語言。`funscript-gen lang template` 由 zh-TW 與 en 產生 `_template.toml`，`lang check` 檢查語言包。程式中用名稱找的表格欄位用不隨語言改變的代號（`report.SCENE_COLUMNS`、`webui.PREVIEW_COLUMNS`），顯示的標題另查語言包。`tests/test_i18n.py` 檢查兩個語言包的 key 與 `{參數}` 一致、範本是最新的、程式要的 key 都存在、程式碼裡沒有殘留的中文字串；`tests/conftest.py` 把測試固定在 zh-TW。
- **本機路徑只在桌面模式開放**：`webui.LOCAL_FILES`（`app` 設為 True）關閉時，「產生」「批次」「預覽」的本機路徑會被拒絕，因為 `webui` 可能開放給區網其他電腦，不能讓它們讀伺服器上的任意檔案。桌面模式用路徑框取代三個分頁的上傳元件（`path_row`）：框外的列（`.fg-drop`，id `drop-<區域>`）是拖放區，選檔按鈕呼叫 pywebview 的原生對話框（`app.file_picker`，kind 為 video／videos／script／folder）。視窗的拖放只有 Python 端知道檔案路徑（WebView2 的 `pywebviewFullPath`）：`app.listen_for_drops` 在 `document` 掛 `drop` 處理器，把路徑交給頁面的 `fgDropped`（`webui.UI_JS`），它記得放在哪個區域，把 `{zone, paths, n}` 寫進隱藏的 `#fg-inbox`；要用 `.change` 觸發（程式設的 `input` 事件 Gradio 不會處理），伺服器端的 `drop_arrived` → `dropped` 決定各框的內容（影片與 funscript 依副檔名分類、批次加到清單、預覽的「自動帶入同名的檔案」用 `sibling`）。選檔按鈕、在框內按 Enter 都走同一個 `dropped`。`NATIVE_DIALOGS` 在建頁面前由 `app.run` 決定（視窗是之後才建的）。

## Windows 免安裝版的建置

`packaging/windows/` 與 `.github/workflows/windows.yml`。用 PyInstaller（`--onedir`）凍結成一個資料夾：兩個 exe 共用 `_internal\`，約 3,200 個檔案、538 MB、zip 240 MB（2026-11-08，GitHub Actions）。2026-11-08 以前附一份完整的 Python（python-build-standalone ＋ C# 啟動程式），刪過能刪的檔案仍有 15,874 個、解壓縮 7.6 秒，所以改用 PyInstaller（見 PLAN 的「已放棄的方案」）。

| 檔案 | 作用 |
|---|---|
| `build.ps1` | 建立虛擬環境，依 `uv export --frozen --extra gui` 的版本與雜湊安裝套件（排除 sympy、mpmath，用 `--no-deps`）→ 安裝專案的 wheel 與 PyInstaller（6.22.3、hooks-contrib 2026.9）→ 執行 `pyinstaller/funscript-gen.spec` → 放進說明、授權與語言包 → 打包成 zip 與 `.sha256`。`-KeepVenv` 把虛擬環境留成 `<OutDir>\build-venv`，給冒煙測試產生測試影片 |
| `pyinstaller/funscript-gen.spec` | 一個 spec 兩個 exe：`FunscriptGen.exe`（無主控台，執行 `funscript_gen.app`：不經過 CLI，因為 `cli.py` 一載入就匯入整個分析流程，視窗要在那之前開啟）與 `funscript-gen.exe`（主控台，CLI）。`gradio`、`gradio_client`、`safehttpx`、`groovy`、`uvicorn`、`webview` 用 `collect_all`（執行時依名稱載入檔案與模組，凍結時容易漏）；gradio 另附 `.py`（`component_meta.py` 每次匯入都讀各元件的原始碼），排除 SSR node 應用與 `.br`；`-X utf8` 用 EXE 的 OPTION |
| `pyinstaller/entry.py` | 兩個 exe 的入口：找到自己所在的資料夾，設定 `FUNSCRIPT_GEN_HOME`、`TEMP`、`TMP` 指向 `data\`、`FUNSCRIPT_GEN_LANG_DIR` 指向 `lang\`，才匯入程式；無法建立 `data\` 時用訊息方塊（無主控台）或 stderr 顯示中英文錯誤 |
| `smoke-test.ps1`、`smoke_clip.py` | 建置後的檢查：CLI 用合成影片產生腳本（資料夾沒有 Python，用 `-Python` 指定建置用的虛擬環境）、`lang list` 要找得到 `lang\` 的語言包、`FunscriptGen.exe --ui none` 回應含路徑框與 `fg-inbox` 的頁面，以及使用者目錄（`USERPROFILE`、`.cache`、`APPDATA`、`LOCALAPPDATA`）沒有多出任何項目 |
| `README.txt`、`README.zh.txt` | 放進 zip 的使用說明（英文與繁體中文）；`build.ps1` 另外把根目錄的 `LICENSE`（存為 `LICENSE.txt`）與 `THIRD_PARTY_NOTICES.md` 放進 zip |
| `lang\`（build.ps1 從 `src/funscript_gen/lang/` 複製） | 放在 exe 旁的語言包，使用者在這裡加入翻譯 |

```powershell
# 在 Windows 上（需要 uv），於 repo 根目錄
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -OutDir dist -KeepVenv
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\smoke-test.ps1 dist\FunscriptGen-<版本>-win64 -Python dist\build-venv\Scripts\python.exe
```

- **GitHub Actions**（`windows-latest`）：手動執行（workflow_dispatch）時把 zip 上傳成 artifact（保留 14 天）；推送 `v*` 標籤時先確認標籤和 `__version__` 相同，再建立**草稿** Release 並附上 zip，檢查後再手動發布。順序是單元測試 → 建置 → 冒煙測試。
- 建置版沒有 git，`build.ps1 -Commit` 把 commit 寫進 `funscript_gen/build-info.json`，`version.provenance()` 讀它填入輸出檔 metadata 的 `commit`。
- PowerShell 5.1 以 ANSI 讀取沒有 BOM 的 `.ps1`：`packaging/windows/*.ps1` 只用 ASCII（中文訊息放在 Python 中）。
- **凍結的注意事項**：PyInstaller 第一次建置只用「全部收集」的 spec 就成功，沒有漏檔；新增依名稱載入資源的套件時要確認它被收進去（冒煙測試的頁面檢查會抓到 Gradio 與其相依套件的缺漏）。Gradio 的 `.py` 不能省（見上表），`numpy.f2py` 之類被其他套件碰到的模組不能排除。
- **效能**（testhost 量測，2026-11-08）：解壓縮 2.3 秒；warm 的伺服器可連線 4.54 秒、CLI `--help` 1.07 秒（匯入 Gradio 1.9 秒、scipy 0.6 秒、建立頁面 1.1 秒，凍結不會改變這些）。視窗不等這些：`app.run` 在執行緒中啟動伺服器（`app.Startup`），主執行緒馬上開視窗顯示載入頁，伺服器好了再 `load_url`（視窗約 0.6 秒出現）。
- 骨架模式不放進去：CUDA 版 PyTorch 約 2.5 GB，超過 GitHub Release 單一檔案 2 GB 的上限。
- 圖形介面的視窗（WebView2）只能在有桌面的工作階段中開啟，SSH 與 CI 無法測試，冒煙測試只檢查伺服器（`--ui none`）。因此桌面視窗的檔案拖放（pywebview 的 `pywebviewFullPath`、`document` 的 drop 處理器）沒有實機驗證：頁面端的流程用 headless Chromium 驗證（模擬 drop 事件後呼叫 `fgDropped`），`app.drop_handler` 用假視窗做單元測試。
## 版本與發布

版本號採用 [Semantic Versioning 2.0](https://semver.org/lang/zh-TW/)（`MAJOR.MINOR.PATCH`），只寫在 `src/funscript_gen/__init__.py` 的 `__version__`（`pyproject.toml` 以 hatch 的 `dynamic = ["version"]` 讀取，Windows 版的檔名與輸出檔 metadata 也用它）。Git 標籤是 `v` 加上版本號（`v1.0.0`），每個標籤對應一個 GitHub Release。

這個專案的公開介面：CLI 的指令與參數、`options.OPTIONS` 的設定名稱與值、設定檔（`.webui-*.json`、`.env` 的變數）、輸出的 funscript 與 metadata 的格式、存下的分析檔（`.analysis.pkl`）、語言包的 key 與參數。

| 變更 | 版本 |
|---|---|
| 移除或改名上面的介面、改成不相容的格式（舊的設定檔或分析檔不能再用） | MAJOR |
| 新功能、新選項；預設值或偵測規則改變而讓輸出明顯不同 | MINOR |
| 修 bug、翻譯、文件、相依套件更新，以及不動介面的小調整 | PATCH |

- 平常的 commit 不改版本號。CHANGELOG 每個 commit 一個條目（`## 日期 — 標題`），發布時在該版包含的條目上方加一行 `## vX.Y.Z — 日期` 與幾點給使用者看的重點；最新的版本標題以上的條目就是尚未發布的修改。
- 預發布版的版本號用 Python（PEP 440）的寫法 `1.1.0rc1`，標籤是 `v1.1.0rc1`（`windows.yml` 要求標籤等於 `v` + `__version__`），Release 標成 pre-release。
- 發布步驟：
  1. 一個 `Release vX.Y.Z` commit：改 `__version__`，在 CHANGELOG 加上版本標題，`uv run pytest` 通過。
  2. 推送到 `main`，確認 `tests.yml` 的**每個 job**（ubuntu 與 windows）都成功：用 `gh run view <id> --json conclusion,jobs` 或不經管線的 `gh run watch <id> --exit-status`，不要把它接到 `tail`（結束碼會被吃掉，只看到通過的那個 job）。可以先單獨推送功能 commit，讓 Windows 的測試在 Release commit 之前跑完。
  3. `git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`：`windows.yml` 建置 zip 並建立**草稿** Release。儲存庫的規則不允許刪除標籤，推送後無法重打，所以第 2 步沒有全綠就不要打標籤（v1.1.0rc3 就因此作廢，改發 rc4）。`windows.yml` 的冒煙測試偶爾會因為 runner 上出現 `AppData\Mozilla` 而失敗，與程式無關，`gh run rerun <id> --failed` 即可。
  4. 檢查草稿的 zip、`.sha256` 與自動產生的說明（補上使用者看得到的重點，中英文），再發布。
- 已發布的標籤不移動、不刪除；發布後發現問題就出新的 PATCH 版。
- 1.0.0 以前的 CHANGELOG 條目記的 commit 標題屬於未公開的開發歷史，公開的儲存庫從 1.0.0 的單一 commit 開始。

---

## 驗證

`valid/` 中每段影片都附有同名的人工 `.funscript`（影片不提交）。素材清單、分組與設定組寫在 `validation.toml`。專案會公開，所以提交的檔案中素材只用代號（`A01`、`B03`…，字母是來源系列、數字沿用原本的編號），第二台測試主機叫 `testhost`；代號對應的實際檔名寫在不提交的 `deidentify.local.toml`（`[clips]`），`validate` 依它找到 `valid/` 中的檔案，沒有這個檔案時代號就是檔名。`tests/test_private_names.py` 在有對照檔時檢查會提交的檔案中沒有實際名稱。

分組：

| 分組 | 素材 | 用途 |
|---|---|---|
| `dev` | 13 段：方向規則與門檻在這批上調整的原本 13 段 | 方向規則與門檻在這批上調整 |
| `test` | 第三批 11 段 | 沒有用來調規則，但已用於一些決定 |
| `holdout` | 2026-11-01 加入的 7 段 | 只在修改完成、要確認時跑；不得依它的分數選擇規則、門檻或設定 |
| `dev2` | 22 段：2026-11-07 新增的 47 段（34 個沒調過規則的來源系列）中依來源系列分出的一半 | 可以用來調整 |
| `holdout2` | 25 段：另一半 | 規則與 `holdout` 相同，只在最後確認 |

不加 `--clips` 時只跑 dev、test（`default_clips`）；`--clips holdout`、`dev2`、`holdout2` 各跑該組，`all` 跑全部。

```bash
uv run funscript-gen validate base -c default -c user                    # 產生並評分，結果在 out/runs/base/
uv run funscript-gen validate new -c default --baseline out/runs/base     # 改程式後和基準比較
uv run funscript-gen compare-runs out/runs/new --baseline out/runs/base --scenes B03   # 逐鏡頭明細
uv run funscript-gen validate shape -c user --replay out/runs/base        # 只改 render 階段：用存下的分析重算，幾秒鐘
uv run funscript-gen validate final -c default --clips holdout            # 保留組：只在修改完成時確認
```

- 執行器把程式碼複製到 `out/runs/<名稱>/code/` 再跑，所以執行中可以繼續修改；中斷後加 `--resume` 接著跑。要跑修改前的程式，用 `--code` 指向修改前的 git worktree 的 `src`。
- 每段素材的分析存成 `<素材>.analysis.pkl`（約 1 MB），`--replay` 讀它，不必重新解碼與呼叫 AI。
- `--baseline` 的 `identical` 欄列出動作逐點相同的素材，差異要只出現在預期的素材。
- 比較程式修改前後要用同一份 AI 快取各跑一次（見下面「AI」）。
- `compare-runs --baseline` 在每個分組下多印一行「95% interval over source series」：F1、`F1u`、`r` 變化的平均與 95% 區間，以來源系列（代號的前綴字母）為單位重抽樣（同一系列的素材不獨立），少於 3 個系列時不印。區間含 0 時不能當成有差異。這個區間只反映素材的抽樣，不含同一素材重跑的雜訊（AI 回答、GPU 光流）：同一份程式重跑兩次的雜訊下限還沒量。
- 第二台測試主機 testhost 是維護者自己的 Windows 電腦，用法與 CPU 使用率限制寫在維護者的私人工作規則中，不在本儲存庫。

### 評分

`compare`（和驗證執行器）以人工腳本為準計算：

- **轉折點 F1**（2026-11-05 起是簡化後的定義）：輸出與人工腳本的峰谷配對後的 Precision／Recall／F1。配對前先簡化：(1) 停頓（連續相同位置）只算一個轉折點，時間是整段停頓，輸出的峰落在停頓內或前後 150 ms 內都算中；(2) 人工腳本中連續三點以上、每次擺幅不超過 10 單位、間隔不超過 0.2 秒的顫動（整段範圍不超過 20 單位）合併成一個停頓，只留頭尾（作者額外加的，畫面看不出來；A06 的 6 Hz 顫動、B03／D02／D05／G07 中間隔約一個影格的雜訊點）；(3) 人工腳本中，夾在兩個較大擺幅之間、本身小於較小那個鄰近擺幅 0.3 倍的反向（行程中途的小回跳，例如上升時的 16→11→30，作者只是在同一方向的行程中變了速度）不算轉折點；一連串大小相同的小振動則保留。輸出只合併停頓、不做後兩項。實作在 `evaluate.simple_extrema`，常數 `SIMPLIFY_RATIO`。相關係數仍用完整的腳本。(4) 忽略人工腳本與輸出都看不出行程的鏡頭：光流訊號的標準差小於 2 **且**沒有任何部位框的鏡頭（作者依音樂加的行程，畫面看不出來），**只對 `validation.toml` 的 `ignore_low_flow` 列出的素材套用（原本是 3D 動畫系列 G01–G07，2026-11-12 移出驗證後這個清單是空的，機制保留）**（E01 開頭 66 秒光流同樣很低但有小動作，所以不能全部套用），這些鏡頭裡兩邊的轉折點都不算；整支影片都被忽略時不套用。實作在 `validate.ignore_spans`（需要 debug 資料中的 `parts_found`，2026-11-05 以後的執行才有），`f1_noign` 是不忽略的值。
- **`F1_raw`**：2026-11-05 以前的 F1（每個點都算）。要和更早的紀錄比較時用。
- **F1s**：（舊定義，沿用）忽略人工腳本中小於 10 的抖動後的 F1。部分人工腳本在行程上疊了大量細小抖動，每個抖動都算一個轉折點，原本的 F1 會因此偏低。
- **`r`**：相關係數，時間差限制在 ±100 ms 內（2026-10-31 起），整段方向相反時是負的。
- **`r500`**：舊算法（±500 ms），和 2026-10-31 以前的紀錄比較時用。舊算法讓整段方向相反的腳本也得到高相關（1.5 Hz 整段顛倒時 0.96）。
- **`F1u`／`ru`**（2026-11-03 起，之前的結果沒有這兩欄）：把和人工腳本負相關的鏡頭（逐鏡頭 r < 0）上下顛倒後的 F1 與 r，也就是「方向都對時」的分數。只改變方向的修改不會動到它們。一個鏡頭翻轉約讓該段 F1 差 0.2（28 段平均差約 0.008），所以平均 F1 的小幅改變要看 `F1u` 是否跟著變：例如 `region_pick_margin` 0 → 0.1 時 F1 +0.012、`F1u` −0.001，只是 2–3 個鏡頭碰巧翻了方向。

### 目前的驗證結果

以現行程式、同一份 AI 快取，對 85 段各完整跑一次（2026-11-12，`out/runs/full-1112`，Qwen3-VL-8B，F1 是簡化後的定義，見上），**再排除同一天移出驗證的 3D 動畫系列 G（7 段）**，得到下面 78 段的表（用 `compare-runs` 對去掉 G 的同一份結果重算，沒有重跑）。數字依序是 F1 ／ F1s ／ `r` ／ `r500` ／ `F1u` ／ `ru`；dev 13、test 11、holdout 7、dev2 22、holdout2 25 段；`--preset user` 是作者在 Web UI 用的設定，`--no-ai` 是不呼叫 AI（整個畫面當分析區域，沒有略過鏡頭與行程範圍）：

| 設定 | dev 13 | test 11 | holdout 7 | dev2 22 | holdout2 25 | 全部 78 |
|---|---|---|---|---|---|---|
| 預設 | 0.887 ／ 0.869 ／ 0.617 ／ 0.633 ／ 0.893 ／ 0.645 | 0.794 ／ 0.744 ／ 0.592 ／ 0.605 ／ 0.798 ／ 0.598 | 0.811 ／ 0.773 ／ 0.465 ／ 0.479 ／ 0.812 ／ 0.476 | 0.694 ／ 0.682 ／ 0.430 ／ 0.445 ／ 0.742 ／ 0.482 | 0.646 ／ 0.616 ／ 0.346 ／ 0.379 ／ 0.685 ／ 0.464 | 0.735 ／ 0.709 ／ 0.460 ／ 0.481 ／ 0.763 ／ 0.519 |
| `--preset user` | 0.880 ／ 0.843 ／ 0.603 ／ 0.620 ／ 0.888 ／ 0.656 | 0.796 ／ 0.730 ／ 0.575 ／ 0.596 ／ 0.817 ／ 0.633 | 0.816 ／ 0.716 ／ 0.463 ／ 0.473 ／ 0.817 ／ 0.473 | 0.672 ／ 0.634 ／ 0.352 ／ 0.407 ／ 0.757 ／ 0.491 | 0.646 ／ 0.596 ／ 0.304 ／ 0.334 ／ 0.691 ／ 0.461 | 0.729 ／ 0.677 ／ 0.420 ／ 0.451 ／ 0.772 ／ 0.527 |
| 不用 AI（`--no-ai`） | 0.825 ／ 0.814 ／ 0.486 ／ 0.527 ／ 0.860 ／ 0.598 | 0.723 ／ 0.667 ／ 0.606 ／ 0.647 ／ 0.773 ／ 0.670 | 0.787 ／ 0.753 ／ 0.451 ／ 0.459 ／ 0.794 ／ 0.465 | 0.716 ／ 0.705 ／ 0.423 ／ 0.434 ／ 0.748 ／ 0.480 | 0.622 ／ 0.581 ／ 0.305 ／ 0.340 ／ 0.671 ／ 0.444 | 0.712 ／ 0.682 ／ 0.424 ／ 0.452 ／ 0.750 ／ 0.514 |

- **預設與 `--preset user` 的輸出和之前的基準逐項相同**（dev2、holdout2 的 F1 與 `r`；dev、test 在含 G 系列時也相同），所以程式與 AI 快取的結果可以重現。含 G 系列的 85 段表（預設 dev 0.853、test 0.799、holdout 0.790、全部 0.736）已不再使用；G 系列的 7 段在預設下 F1 0.58–0.84，拉低了舊的平均。
- **AI 的貢獻集中在調過規則的素材**：沒用過的 47 段（dev2＋holdout2）的平均，預設 F1 0.668、`--no-ai` 0.668（持平），`r` 0.385 對 0.360，`F1u` 0.712 對 0.707；調過的 dev＋test 則是預設 0.844 對 0.778。區間（`compare-runs`，以來源系列重抽樣）：`--no-ai` 相對預設，dev ΔF1 −0.061 [−0.108, −0.015]、test −0.071 [−0.164, −0.003] 有差；holdout（−0.024 [−0.058, +0.001]）、dev2（+0.022 [−0.004, +0.060]）、holdout2（−0.024 [−0.061, +0.034]）的區間都含 0，分不出差異；全部 78 段 F1 −0.024 [−0.047, +0.004]、`r` −0.036 [−0.070, −0.006]。所以 AI 的好處在調過的素材上才看得到，在沒見過的來源上量不出（各項貢獻沒有拆解，未驗證），詳見 PLAN 的專案審視 B4／C1。
- **`--preset user`** 對預設：全部 78 段 F1 −0.007（95% 區間 [−0.027, +0.012]，分不出差異）、`F1u` +0.009（[−0.006, +0.023]）、`r` −0.040（[−0.075, −0.012]，有差）；所以 README 說它的 F1 相近、相關係數略低，不再說「分數最好」。
- 13 秒、單一鏡頭的短片 F1 0.90–0.99；多鏡頭的長片落差大，最低的是整段方向相反的正面視角與第一人稱。
- 這次的執行中 `default/S01` 被系統以 -9 殺掉（同時跑測試造成記憶體不足），用 `--resume` 補跑；驗證主機只有 9 GB 記憶體，驗證時不要同時跑 `uv run pytest`。
- 之前各版本的分數見[歸檔的開發紀錄](docs/archive/PLAN-archive.md#開發紀錄2026-10-27--2026-11-03)、[附錄](docs/archive/PLAN-archive.md#附錄驗證紀錄2026-10-30-以前)與歸檔最後的「舊的驗證表（2026-11-12 移出）」。

和其他工具比較（2026-11-04，含已移出的 G 系列，數字不能和上表直接比；在斷網的 Docker 容器中執行，用 `scripts/score_external.py` 以相同方式評分）：Funscript-Flow（`0004d38`，GUI 預設）dev 16 段 0.492 ／ 0.502 ／ 0.085 ／ 0.356、test 0.580 ／ 0.565 ／ 0.253 ／ 0.380、holdout 0.499 ／ 0.505 ／ 0.117 ／ 0.204；它沒有方向判斷，每個鏡頭方向都換成對的（`F1u`）也只有 0.717／0.650／0.583，各組都低於本專案的預設。OpenFunML（`0f06321`，ONNX 模型 0.2，在本機以 onnxruntime 執行、照它的預設後處理）dev 0.643 ／ 0.663 ／ 0.332 ／ 0.403、test 0.629 ／ 0.635 ／ 0.448 ／ 0.520、holdout 0.642 ／ 0.689 ／ 0.366 ／ 0.389（`F1u` 0.730／0.728／0.667），也都低於本專案的預設；它的位置輸出當鏡頭方向證據時，和本專案相反的鏡頭中只對 1/3。詳細數字與執行方式見 PLAN.md 2026-11-04。

---

## 已知問題的技術細節

README 只寫使用者看得到的限制；這裡是對應的素材、數字與原因。依影響排序的清單在 [PLAN.md 的「待解決的問題」](PLAN.md#待解決的問題依影響排序)，試過但沒有採用的方法在[「已放棄的方案」](PLAN.md#已放棄的方案)。

**行程方向**
- **「往上＝高」在正常位與第一人稱常常整段相反**（B03、D02、E02、I01 等）：這類畫面往上推進是插入，第一人稱女上位同樣往上卻是拔出，光流分不出兩者。部位框與快慢判斷的規則是在前 13 段素材上決定的（沒有用來調整的 test 12 段 F1 0.638 → 0.688，沒有一段變差）；2026-10-31 以留一支影片交叉驗證檢查，選出的就是目前的門檻，改用加權組合反而較差。剩下的錯誤多半沒有證據可判斷。
- **剪接後的單一鏡頭沒有鄰段可對齊**，方向不明確時等於用猜的；比對前後鏡頭的動作型態也分不出來。
- **接觸點的遮擋也幫不上方向**：光流正反向一致性標出的「被遮住／新露出」像素，在輸出方向錯的鏡頭上只有 47% 指向正確方向（dev 49 個鏡頭），量到的主要是一般的運動邊緣（`scripts/occlusion_sign.py`）。
- **用人工腳本訓練的深淺預測也幫不上方向**：DINOv2、CLIP 與動漫標籤模型（WD tagger v3）的凍結特徵以嶺迴歸擬合人工腳本的位置（每次留一個來源系列），預測和人工腳本相關只有 0.2–0.45，當方向線索比輸出本身差；只翻信心高的鏡頭時 dev F1 +0.024，主要是 B02 的一個鏡頭，test／holdout 持平（+0.004／+0.005），WD 版會把單一鏡頭的 J01 整段翻錯（`scripts/depth_compare.py`，特徵在 testhost 的 GPU 上抽）。
- **單目深度估計也幫不上方向**：Depth Anything V2 Small 的區域深度（愈近＝愈低）和人工腳本同向約 70–80%，但 2D 上翻錯 J01、B01 這種單鏡頭短片（test F1 0.710 → 0.620）；只用在 G 系列時 dev 0.723 → 0.730、holdout 0.655 → 0.662，改對的鏡頭和 G 系列降低快慢門檻（dev 0.742、holdout 0.669）幾乎相同，疊上去沒有增加（`scripts/depth_sign.py`，深度在 testhost 的 GPU 上算）。
- **把各種方向線索依信心加權投票也沒有比較好**：部位框、快慢、聲音、OpenFunML、DINOv2／WD 深淺模型一起投票（三種校準、約 100 組設定，每次留一個來源系列），沒有一組在 dev 與 test 都不低於現行規則（dev 0.723、test 0.710）。單獨可信的只有部位框（87–100%）與明顯的快慢不對稱（≥ 0.4 時 92–100%），其他線索 55–80% 而且錯在同一批鏡頭；「往上＝高」在 A 系列多半對、在 G 系列多半錯，固定權重兩邊都顧不到，翻錯 B01、J01 這種單鏡頭短片就是整段 −0.96 以上（`scripts/sign_vote.py`）。
- **聲音分離也幫不上方向**：用 Demucs 分出鼓或去掉人聲後再看撞擊聲落在行程哪一端，dev 略好、test 變差，整段分數在雜訊範圍內（`scripts/audio_stems.py`）；撞擊聲的位置本來就依體位而不同。
- **AI 判斷不出方向**：請 8B 判斷插入深度、體位、誰在動、陰莖露出的長度，以及用原生影片輸入請 8B、32B 判斷插入或拔出，都比現行規則差。
- **3D 動畫沒有驗證素材了**（2026-11-12 移出驗證的 G 系列 7 段，不再用它驗證）：移出前它是方向最差的來源，F1 0.50–0.84，約 1/3 的鏡頭方向錯；鏡頭切得很碎（中位 1.4–7 秒），部位框檢查需要較長的鏡頭，所以大多沒有判斷方向的證據；2026-11-05 的「聲音沒有反對就用 0.2 的快慢門檻」就是為它調的，現在已無法在 3D 素材上確認。這個門檻、以及它對 3D 動畫的影響，之後只能當作未驗證。
- **部位框判斷**判斷「一致」的鏡頭也可能是錯的（B03 1 個、I01 2 個）。
- **快慢門檻的聲音否決**：聲音中性時用 0.2 會翻錯沒有撞擊聲、但人工腳本往上快的鏡頭（F01 第 1 段，r 0.20 → −0.02；F01 的人工腳本本來就是依聲音推測的），Hybrid 下 H02 r −0.27。以畫風（3D／2D）分開門檻不可行：Qwen3-VL-8B 與 deepghs `anime_classification` 都分不出 G 系列，數字見 PLAN.md 2026-11-05。
- **聲音提示（`--sound-hint`）**：在決定門檻的 dev／test 上標出的鏡頭多半確實相反，在 holdout 的 9 段標出 14 個鏡頭卻全部方向正確（C02 的長鏡頭、D05），真正相反的 G 系列一個也沒標到，所以預設關閉。

**準確度**
- **沒調過規則的新來源 F1 約 0.67**（47 段，dev2 0.694、holdout2 0.646；調過的 dev＋test 是 0.830）：失分主要是節奏不明顯的鏡頭（流程訊號被慢速成分主導）漏掉行程，輸出轉折點只有人工腳本的 1/3–1/6；方向對時的 `F1u` 0.711。上限實驗（`scripts/region_oracle.py`）顯示這類鏡頭的網格區域中有量得到行程的（依節奏集中度挑的 |r| 中位數 0.74，使用的區域 0.42），但新區域的符號只有一半和人工腳本同向；行程率的估計（`scripts/freq_cues.py`、`scripts/peak_cue.py`）、Hybrid 測量、神諭頻率都沒有可靠增益（見 PLAN 2026-11-07～08）。
- **長片的分數明顯低於短片**：失分主要來自方向、分析區域混入別的動作，以及每一下的大小和人工腳本不同；光流、部位框與聲音都看不出每一下的深淺。SAM2 逐幀分割陰莖的遮罩比部位框更貼近人工腳本，但換成位置後分數沒有提高，而且每秒 10 張時在 RTX 3070 上約要影片長度的 4 倍時間（`scripts/mask_depth.py`）。
- **人工腳本的細小抖動與停頓讓 F1 偏低**（看 F1s）；慢行程在底端停頓時，人工腳本常把轉折點標在停頓結束。疊在慢速大動作上的小行程抓不到（K01、A06 第 20–30 秒、B04）。
- **轉折點的時間**：方向對的鏡頭中和人工腳本相差中位約一幀（33 ms），各處理階段都沒有把它推遠。人工腳本有整段的偏移（L01 約 −150 ms、I01 +150 ms，像作者的習慣），各鏡頭也有 ±100 ms 內方向不一的偏移；聲音起點預測不了這些偏移（`scripts/turn_timing.py`）。和人工腳本相關低的鏡頭失分在轉折點數（漏掉的行程），不在時間。
- **行程範圍辨識的 AI 判斷幾乎是常數**：28 段 367 個有效鏡頭中有 311 個（85%）判為看不到龜頭（截到 80），18 段整支與固定截到 80 逐點相同，AI 的回答也和人工腳本的頂端位置無關（判完整露出的鏡頭人工 p95 中位數 80.0，反而低於判看不到龜頭的 87.2）。2026-11-05 評估完全移除或改以固定上限／部位框重建：完全移除時 F1 持平或略升、dev 的 r 略降，固定截到 80 則與現行分數幾乎相同；依使用者決定保留原狀（數字見 PLAN.md 2026-11-05）。這個 AI 呼叫也承載未成年判斷的欄位。
- **新來源的 F1 落差有一部分是人工腳本的細碎抖動**（2026-11-09）：下一個點在 150 ms 內的人工轉折點佔 dev 25%、dev2 49%、holdout2 39%（例如 15 Hz 的鋸齒疊在大行程上），畫面看不出來；把評分中顫動的合併放寬（擺幅 20、間隔 150 ms）後 F1 dev 0.851 → 0.866、dev2 0.694 → 0.721、holdout2 0.646 → 0.693。評分方式沒有改（和歷史分數可比）。
- **長影片的資源**（2026-11-09，Linux、12 核、vLLM 在區網）：1 小時的 854×480 影片（27 段接起來、331 個鏡頭）端到端 25 分 56 秒（AI 沒有快取）、峰值記憶體 3.5 GB（glibc 限制 2 個 arena 之後；之前 5.1 GB）；AI 已快取時 6 分鐘。記憶體隨影片長度增長（約 0.6 GB／15 分鐘：15 分鐘 1.6 GB、1 小時 3.5 GB）。
- **節奏濾波**可能略過或鎖錯節奏：集中度 50–80% 時要行程頻率也符合才濾波。
- **高頻縮小幅度比人工腳本保守**：人工腳本到 4 Hz 只短約一成，再快才明顯縮短；預設 3 Hz 以上縮成 50% 是為了裝置與體感設的。
- **5 Hz 以上的快速行程**：動作之間最少 60 ms（2026-11-04 以前 90 ms，D03 #1 約 5 Hz 的行程因此每秒只剩 4.45 個轉折點）；沒有節奏、又疊在慢速漂移上的快速行程仍常被突出度刪掉（D03 在預設設定下沒有改善）。把這類訊號高通後再做節奏濾波會鎖到作者沒寫的小動作（B04、A03），不採用。
- **限速**預設 500 單位／秒（OSR2 一般伺服馬達的社群估計，沒有官方規格）：人工腳本的速度上限約 600（p99 602），但輸出只有約 0.2% 的移動時間達到 500，因為快速行程先被高頻縮小縮短；600–1000 的分數和 500 相差 ≤ 0.001。
- **鏡頭切換處銜接**只看前一個鏡頭的節奏，人工腳本於切換處停下或放慢時會多出一下（holdout 的 N01 F1 略降）。
- **區域選到另一個節奏的動作**：A06 開頭 10 秒選中的區域是 2.5 Hz，人工腳本跟的小塊是 1.5 Hz（光流頻譜，`scripts/tempo_windows.py`）；dev＋test 的 5 秒窗口中約 17% 輸出與人工腳本的主頻不符，集中在 G 系列、A01、E01、B04。
- **`--dwell`** 讓 F1 略降（評分把停頓的兩點各算一個轉折點），相關係數則上升。
- **候選區域再確認**偶爾換成較差的區域（例如 E01 第 1 個鏡頭），規則只在 8 段素材上決定。
- **`--scene-center`** 提高相關係數但不改善 F1，分不出真的慢動作與光流的漂移（F01）。
- **驗證素材沒有低於 30 fps 的影片**：38 段都是 30／60 fps 的來源（量到的幀率 30 或 29.97），一般動畫的 23.976 fps 沒有被驗證過；2026-11-03 起去漂移視窗與快慢判斷改用實際幀率（之前把 24 fps 當 30 算，視窗變成 3.75 秒），只有單元測試覆蓋。
- **AI 的幫助不穩定**：dev 上不用 AI 的 F1 較低，test 上反而較高（見上面的表），差別主要在方向。

**AI**
- **快取競爭**：vLLM 同時處理多個請求時答案可能不同；兩個設定同時跑同一段影片時，快取留下較晚的答案。比較程式修改前後，要用同一份快取各跑一次（`--baseline`）。
- **Qwen3-VL-30B-A3B** 常把整個人的框當成分析區域（8 段 F1 0.66，8B 0.87）。
- **Ollama**（`VLLM_BACKEND=ollama`，實測 0.40.13）：Qwen3-VL 每張圖約 1040 個 token（與大小無關），候選區域再確認最多 8 張圖約 8.4k，所以 `VLLM_NUM_CTX` 預設 16384；它的 `/v1` 用預設上下文（4096）會拒絕 4 張圖，而且不保留標籤與圖片的順序。預設只有 1 個運算槽，逾時乘上同時請求數。RTX 3070 只放得下 4B：A01／A04／G06 F1 0.682／0.682／0.451（vLLM 8B 0.798／0.776／0.471），Ollama 上 8B 的準確度未驗證。
- **Hybrid** 只比一般模式略好（13 段 F1 0.745 → 0.759）：AI 的「看得清楚」判斷不太能預測哪個區域效果好；每個鏡頭只有 4 個關鍵幀，切換的時間解析度很粗；改用部位框逐幀選擇也沒有改善（換成部位框的區域會改變整段方向，只換逐幀選擇幾乎沒有變化）。
- **手和口改看移動較大的那個**（`--contact-pick`，Hybrid）：預設第二名的機率 ≥ 0.1 才比較（`--contact-min-prob`），dev＋test 只有 A01 75.1 s、G06 81.5 s 兩個鏡頭觸發（G06 r 0.65 → 0.95），holdout 只有 G05 一個；整體分數到小數第三位幾乎不變。下限設 0 時多觸發的鏡頭有的變差（G06 78.2 s、E01 65.8 s）。數字見 PLAN.md 2026-11-04。
- **未成年人判斷目前沒有作用**：判斷欄位只在行程範圍辨識與 Hybrid 的生殖器分析這兩個 AI 呼叫中；2026-10-27 起兩者的提示詞都要求模型固定回答 False（commit `edit 18`），略過時的備註也改成「繼續」（`pipeline18off`），檢查這條路徑的 2 個測試已略過。恢復與改進的建議見 PLAN.md。

**效能**
- 12 核 CPU 上，2 分鐘、16 個鏡頭的 A04 約 22 秒（AI 已快取、不含部位框）；沒有快取時 AI 階段約 30 秒，和光流同時進行。
- 光流佔分析時間的大部分（Farneback 單執行緒每秒約 59 幀，480 寬；解碼整支影片只要幾秒）。2026-11-03 起每層金字塔迭代 2 次（`flow.FARNEBACK`，原本 3 次）：每幀 15.9 → 12.0 ms，整個流程（AI 與部位框已快取）快 9–13%，分數持平；大幅動作的 C01 光流場和 3 次的相關只有 0.90，但輸出的分數沒變。每個鏡頭切成最多 5 秒的小段（`pipeline.FLOW_PIECE_S`）平行計算再接回（`FlowTracker.extend`，逐點相同），只有一兩個鏡頭的短片不再只用一個核心：不含部位框時 A02 8.0 → 4.3 秒、K01 35.8 → 16.8、B03 79.9 → 65.8，鏡頭多的 A04 原本就滿載、不變。
- DIS 光流快約 5.6 倍，但 dev F1 0.720 → 0.615，不採用。
- `--flow-width 320` 約快 2 倍、訊號品質相當，但方向不明確的影片可能換方向（B02），所以預設 480。
- 直式影片解碼成 360×640，比 `--flow-width` 窄時直接在 360 寬上算光流、再換算回 480 寬的像素與格子（`FlowTracker.update`），不放大到 480×853（2026-11-03 以前會放大，像素多約 1.8 倍）。AI 與部位框已快取時 B03 67.6 → 41.6 秒、K01 17.8 → 11.4、A06 17.5 → 11.7；7 段直式素材的輸出改變，分數在雜訊範圍內。
- 部位框判斷在 CPU 上：3 分鐘的 B03 關閉時 66 秒，開啟（部位框沒有快取）時 120 秒。本機 CPU 推論每幀 57 ms／215 ms CPU，同時跑幾個（共用或各自的 session）都只到每秒約 25 幀，多開工作數沒有用，只能減少偵測的幀數或用 GPU。RTX 3070 上每幀 CPU 約 100 ms、DirectML 23 ms，DirectML 的框和 CPU 完全相同。部位框也切成 5 秒小段平行偵測（`parts.PIECE_S`，快取仍以整個鏡頭為鍵），單一鏡頭的 A02 13.0 → 11.5 秒。
- 影片會解碼兩次（切分鏡頭、計算光流），部位框判斷再多一到兩次；解碼不是瓶頸（3 分鐘 60 fps 的 B03 每次約 7 秒）。硬體解碼（NVDEC、D3D11VA）的畫面相同但較慢，沒有採用。
- 光流的 GPU 模式（`--flow-compute`，預設 Auto）用 OpenCV 的 OpenCL：RTX 3070 上 Farneback 107 fps，單執行緒 CPU 37 fps；testhost 6 段在 80% CPU 上限下整批 390 → 292 秒。GPU 的光流場和 CPU 平均差 0.004 px，輸出不逐點相同（6 段 F1 0.575 → 0.576、各段 |ΔF1| ≤ 0.004），同一台 GPU 重跑逐點相同。本機沒有 OpenCL，Auto 用 CPU。

---

## 對外用詞對照

專案會公開，README、ARCHITECTURE、Web UI、CLI 說明、語言包與預覽播放器（使用者看得到的文字）一律用下表的中性詞；程式識別字（`penis`、`vulva`、`glans`、`genital`、`insertion` 等）、AI 提示詞（`ai/prompts.py`）、偵測模型的類別名稱、語言包的 key（例如 `pipe.range_no_glans`、`preview.js.region_genital`）、PLAN／CHANGELOG 與本檔的技術說明維持原詞：提示詞需要精確的詞模型才答得準，類別名稱要和模型輸出對應，開發紀錄改寫會失真。

| 對外用詞（zh-TW／en） | 原先代表 | 說明 |
|---|---|---|
| 主動部位／active part | 陰莖（penis） | 畫面中做往復運動的主要對象，也是行程方向與深淺的依據 |
| 對象部位／counterpart | 陰道（vulva） | 主動部位接觸的另一方；部位框判斷方向用「兩者的距離」 |
| 前端／tip | 龜頭（glans） | 主動部位的前端；「看不到前端」＝行程到不了頂端，行程範圍辨識據此截斷 |
| 目標部位、目標區域／target part, target region | 生殖器、生殖器區域（genital region） | Hybrid 另外框出的區域，看得清楚時改看這裡 |
| 推進、退回／push in, pull back | 插入、拔出（insertion, pull-out） | 往復動作的兩個方向；「往哪邊是推進」決定高低方向 |
| 口部接觸、手部接觸／mouth contact, hand contact | 口交、自慰（oral, masturbation） | 接觸部位是口或手的鏡頭；這類鏡頭沒有對象部位框 |
| 正面視角、背面視角、上方視角／front view, rear view, top view | 正常位、後背位、女上位（missionary, rear-entry, cowgirl） | 鏡頭相對於動作的視角；正面與第一人稱常整段高低相反 |

新增或修改使用者看得到的文字時沿用這些詞，並在這個表補上新詞。`tests/test_i18n.py` 不檢查用詞，所以改文字後用下面的指令確認沒有露骨用詞殘留在使用者看得到的檔案（語言包 key 與 PLAN 等不算）：

```bash
grep -n -E '陰莖|陰道|龜頭|生殖器|插入|拔出|口交|自慰|penis|vulva|glans|genital' README*.md ARCHITECTURE.md docker/README*.md packaging/windows/README* src/funscript_gen/lang/zh-TW.toml src/funscript_gen/lang/en.toml
```

## 專案結構

各模組在流程中的位置見 [ARCHITECTURE.md](ARCHITECTURE.md)。

```
src/funscript_gen/
  cli.py              CLI 進入點
  webui.py            Gradio Web UI 的處理函式與狀態（工作、設定、輸出、預覽、工具、批次、伺服器）
  webui_layout.py     Web UI 的頁面：元件與接線（`build`）、CSS／JS、路徑框與設定表單；處理函式在呼叫時才從 webui 取（避免載入時互相匯入，測試對 webui 的 monkeypatch 仍然有效）
  ollama_setup.py     一鍵執行 Ollama（Docker 容器或已安裝的 ollama serve、下載模型），供 Web UI「設定」分頁使用
  subproc.py          執行 docker、git 等主控台程式（Windows 上不彈出主控台視窗）
  app.py              桌面模式（funscript-gen app）：本機的 Web UI，在 pywebview 視窗或瀏覽器中開啟，原生選檔對話框與拖放（檔案以路徑讀取，沒有上傳）
  paths.py            程式寫入的檔案位置（FUNSCRIPT_GEN_HOME）
  i18n.py             多語言：語言包的載入、`t()` 查表、語言選擇、範本與檢查
  lang/               語言包：zh-TW.toml（原稿）、en.toml、_template.toml（範本）
  options.py          所有使用者設定的表：CLI 參數、Web UI 表單、設定組與 metadata 都由它產生
  batch.py            批次產生：找影片、決定輸出檔名、依序產生（CLI batch 與 Web UI「批次」分頁共用）
  direction.py        行程方向的判斷：長鏡頭分段對齊、部位框、快慢不對稱與聲音，以及手動反轉（`toggle_flip`、`carry_flips`）；改 `ScenePlan` 的欄位，類別本身在 pipeline.py（存下的分析檔以那裡的路徑記錄類別）
  pipeline.py         整體流程：analyze_video（鏡頭 → AI，同時計算各鏡頭的光流 → 部位框、聲音）→ render（訊號 → 方向 → funscript）
  evaluate.py         與參考腳本比較
  validate.py         驗證執行器與執行結果的比較
  version.py          版本、程式碼雜湊與 git commit（寫進輸出檔的 metadata）
  config.py           .env 設定與 provider 建立
  devices.py          運算裝置：光流、部位框、骨架用 GPU 或 CPU（Auto／GPU／CPU 的繼承與 GPU 偵測）
  report.py           訊號圖、鏡頭表、除錯資料（CLI 與 Web UI 共用）
  preview.py          預覽播放器（自成一體的 HTML／JS；多軸腳本的軸列）與工具分頁的多軸檢視頁
  multiaxis.py        多軸腳本：從檔名與內容辨識（每軸一檔／一檔多軸）、合併、分割、帶入同資料夾的軸檔、備份與寫檔（預覽與「工具」分頁共用）
  cache.py            快取資料夾的用量與清除（`funscript-gen cache info／clear`；只清 ai、parts、poses，不動下載的模型）
  outputs.py          Web UI 輸出資料夾的保留天數、清理與「存到影片旁邊」設定
  ai/                 視覺語言模型 provider（OpenAI 相容、Ollama 原生）、提示詞與 schema、回應快取、候選區域（regions.py）
  video/              解碼（精確時間戳）、鏡頭切分
  tracking/           光流、動漫部位框（parts.py）、骨架偵測與兩人相對位移（選配）
  signal/             訊號後處理、聲音（audio.py：撞擊聲的起點與相位）
  export/             funscript 讀寫
scripts/                維護中的開發工具（`tests/test_scripts.py` 檢查語法與這份清單，CI 用 ruff 檢查）
  check_history.py      發布前的檢查：掃描整個 git 歷史有沒有真實名稱、金鑰、非 noreply 的信箱
  detect_viewer.py      偵測模型檢視器，用法見「開發環境與測試」
  flow_dump.py          把每幀的粗略光流場存成檔案，供離線實驗
  make_synthetic.py     骨架模式的火柴人合成影片（需要 --extra pose）
  param_sweep.py        render 階段參數的一次一個掃描（用存下的分析，離線）
  remote_validate.ps1   在第二台測試主機上以 CPU 使用率上限執行驗證
  rescore_run.py        用目前的評分方式重算舊的執行結果
  scene_diag.py         逐鏡頭診斷：相關、轉折點密度、時間差、節奏與備註
  score_external.py     用驗證的評分方式評分其他工具的輸出，寫成 compare-runs 能讀的執行目錄
  sign_model.py         以存下的分析比較方向判斷的規則（留一支影片交叉驗證）
  two_cues.py           逐鏡頭比較兩個執行（例如有 AI 與不用 AI）的方向與相關
  experiments/          一次性的實驗腳本（部位框、小行程、鏡頭移動、深度、微調模型等），結果寫在 PLAN 與歸檔；不維護，可能已無法執行（說明見該資料夾的 README）；2026-11-12 以前的 PLAN、CHANGELOG 與歸檔寫的 `scripts/<名稱>.py` 現在在這裡
tests/                  單元測試
packaging/windows/      Windows 免安裝版的建置腳本、啟動程式原始碼、冒煙測試、zip 內的說明（README.txt 英文、README.zh.txt 繁體中文）
.github/                 issue／PR 範本、Dependabot；workflows/：tests.yml（Linux 與 Windows 跑單元測試）、windows.yml（建置 Windows 免安裝版、草稿 Release）
CONTRIBUTING.md、SECURITY.md  貢獻說明（含貢獻的授權）與安全性政策（中英雙語）
docker/                 Dockerfile、docker-compose.yaml（只有 funscript-gen）、docker-compose.ollama.yaml（加上 Ollama）、entrypoint.sh、使用說明
docs/archive/           歸檔的開發紀錄（PLAN-archive.md）
LICENSE                 PolyForm Noncommercial 1.0.0 授權條款
THIRD_PARTY_NOTICES.md  第三方開源套件、參考程式碼與外部模型的授權聲明
validation.toml         驗證素材清單、分組與設定組（素材用代號）
deidentify.local.toml   代號與實際素材、主機名稱的對照（私人，不提交）
```
