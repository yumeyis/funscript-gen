# 用 Docker 執行 funscript-gen

**繁體中文** | [English](README.md)

這個資料夾可以把 funscript-gen 建置成 Docker 映像檔，不必在主機上安裝 Python 與套件。有兩種組合：

| 檔案 | 內容 | 適合 |
|---|---|---|
| `docker-compose.yaml` | 只有 funscript-gen | AI 後端（vLLM、Ollama 等）已經架在別台主機或另外執行 |
| `docker-compose.ollama.yaml` | funscript-gen ＋ Ollama（Qwen3-VL） | 一台有 NVIDIA 顯示卡的電腦就全部跑起來 |

其他檔案：`Dockerfile`（映像檔）、`entrypoint.sh`（容器啟動時執行）、`Dockerfile.dockerignore`（建置時只送進必要的檔案，影片、輸出與 `.env` 不會進映像檔）。

## 需求

- Docker 與 Docker Compose v2（`docker compose`）；只在 Linux 上實測過。
- Ollama 版另外需要 NVIDIA 顯示卡、驅動程式與 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)。8B 模型約要 8.5 GB 可用的顯示卡記憶體（見專案 [README](../README.zh.md#用-ollama)）。

## 一般版（只有 funscript-gen）

以下指令都在 `docker/` 資料夾中執行：

```bash
cd docker
mkdir -p data videos                 # 先建立，否則 Docker 會以 root 建立，容器無法寫入
docker compose up -d --build         # 建置並在背景啟動
```

開啟 http://127.0.0.1:7860 ，到「設定」分頁填入 AI 端點（例如 `http://<vLLM 主機>:8000/v1`）、金鑰與模型，按「儲存設定」。設定存在 `data/.env`，之後啟動沿用。

> 端點在主機本身上時（例如主機上執行的 vLLM），容器內的 `127.0.0.1` 指的是容器自己，不是主機：請填主機的區網 IP。

停止與更新：

```bash
docker compose logs -f               # 查看記錄
docker compose down                  # 停止（data/ 中的設定與輸出保留）
git pull && docker compose up -d --build   # 更新程式後重新建置
```

## Ollama 版（funscript-gen ＋ Ollama）

```bash
cd docker
mkdir -p data videos
docker compose -f docker-compose.ollama.yaml up -d --build
```

第一次啟動時 `ollama-pull` 會先下載模型（`qwen3-vl:8b-instruct` 約 6 GB），下載完 funscript-gen 才會啟動；進度用 `docker compose -f docker-compose.ollama.yaml logs -f ollama-pull` 查看。模型存在 `ollama/`，之後啟動不會重新下載。

funscript-gen 第一次啟動時會建立 `data/.env`，後端設為 Ollama、端點設為 `http://ollama:11434`，不必再到「設定」分頁填寫。Ollama 的連接埠沒有對外開放，只有 funscript-gen 連得到。

8 GB 的顯示卡請改用 4B 模型（準確度較低）。`OLLAMA_MODEL` 只在第一次建立 `data/.env` 時寫入；已經建立過時，另外到「設定」分頁把模型改成 `qwen3-vl:4b-instruct`：

```bash
OLLAMA_MODEL=qwen3-vl:4b-instruct docker compose -f docker-compose.ollama.yaml up -d --build
```

## 可以調整的變數

寫在 `docker/.env`（docker compose 自動讀取；這個檔案和專案的 AI 設定 `data/.env` 不同），或在指令前面加上，例如 `WEBUI_PORT=7861 docker compose up -d`：

| 變數 | 預設 | 說明 |
|---|---|---|
| `WEBUI_BIND` | `127.0.0.1` | Web UI 開放的位址；`0.0.0.0` 讓區網其他電腦連線。Web UI **沒有登入**，能連到的人都能使用並修改 AI 端點與金鑰，只在信任的網路中開放 |
| `WEBUI_PORT` | `7860` | 主機上的連接埠 |
| `VIDEOS_DIR` | `./videos` | 掛到容器 `/videos` 的資料夾（給 CLI 用） |
| `UID` / `GID` | `1000` | 容器以這個使用者執行，`data/`、`videos/` 中的檔案屬於它；主機帳號不是 1000 時設成 `id -u`／`id -g` 的值 |
| `WITH_POSE` | `0` | `1`：映像檔加裝骨架模式（`--mode pose`）需要的 CPU 版 PyTorch 與 YOLO（大約多 0.8 GB），改了要加 `--build` |
| `INIT_VLLM_BASE_URL` / `INIT_VLLM_API_KEY` / `INIT_VLLM_MODEL` | 無 | 一般版：第一次建立 `data/.env` 時寫入的 AI 設定（之後改用「設定」分頁） |
| `OLLAMA_MODEL` | `qwen3-vl:8b-instruct` | Ollama 版：下載的模型，也是第一次建立 `data/.env` 時寫入的模型 |
| `OLLAMA_VERSION` | `0.40.13` | Ollama 版：Ollama 映像檔的版本 |
| `FUNSCRIPT_GEN_LANG` | 空 | 介面語言（`zh-TW`、`en`，或放在 `data/lang/` 的語言包代碼）；空白時用 Web UI「設定」分頁選的語言，沒選過就用英文（容器沒有系統語言設定） |

## 用 CLI

把影片放進 `videos/`（或 `VIDEOS_DIR` 指定的資料夾），用 `exec` 在執行中的容器裡下指令（Ollama 版加上 `-f docker-compose.ollama.yaml`），參數和專案 README 的 CLI 相同：

```bash
docker compose exec funscript-gen funscript-gen generate /videos/a.mp4 --preset user   # 輸出 videos/a.funscript
docker compose exec funscript-gen funscript-gen batch /videos
docker compose exec funscript-gen funscript-gen --help
```

沒有啟動 Web UI 時，用 `run` 執行一次就結束（`entrypoint.sh` 會把 `webui` 以外的指令直接交給 `funscript-gen`）：

```bash
docker compose run --rm funscript-gen generate /videos/a.mp4
```

## 資料存放位置

容器只有 `/data` 需要保留，對應到主機的 `docker/data/`：

| 位置 | 內容 |
|---|---|
| `data/.env` | AI 設定（含金鑰，權限 600） |
| `data/.webui-last.json`、`data/.webui-cleanup.json` | Web UI 記住的設定與輸出的保留天數 |
| `data/out/webui/` | Web UI 產生的腳本 |
| `data/lang/` | 自己加入的語言包（`.toml`，選用；範本見專案的 `lang/_template.toml`，用 `docker compose exec funscript-gen funscript-gen lang template /data/lang/_template.toml` 產生） |
| `data/.cache/funscript-gen/` | AI 回答與部位框的快取（可刪除） |
| `data/.cache/huggingface/` | 部位框偵測模型（第一次使用時下載，約 43 MB） |
| `data/tmp/` | Web UI 上傳的影片暫存檔（不會自動清除，可以直接刪除） |

`docker/data/`、`docker/videos/`、`docker/ollama/` 與 `docker/.env` 都已列在專案的 `.gitignore`。

## 限制

- **只用 CPU 計算**：映像檔中沒有 GPU 的 OpenCL 與 onnxruntime GPU 版，光流與部位框判斷在 CPU 上算（「運算裝置」的 Auto 會自動用 CPU；選 GPU 會提示找不到 GPU 並停止）。Ollama 版只有 Ollama 用 GPU。
- 骨架模式需要用 `WITH_POSE=1` 重新建置。

## 修改建置方式時

改到安裝方式（`pyproject.toml` 的相依套件或選配項目、新的系統套件、程式寫入檔案的位置、Web UI 的啟動參數等）時，要一併檢查並更新這個資料夾的 `Dockerfile`、兩個 compose 檔與本說明。
