# Running funscript-gen with Docker

[繁體中文](README.md) | **English**

This folder builds funscript-gen into a Docker image, so there is no need to install Python and the packages on the host. There are two combinations:

| File | Contents | Suited for |
|---|---|---|
| `docker-compose.yaml` | funscript-gen only | The AI backend (vLLM, Ollama, etc.) already runs on another host or separately |
| `docker-compose.ollama.yaml` | funscript-gen + Ollama (Qwen3-VL) | One computer with an NVIDIA graphics card runs everything |

Other files: `Dockerfile` (the image), `entrypoint.sh` (run when the container starts), `Dockerfile.dockerignore` (only the necessary files are sent to the build; videos, outputs and `.env` never go into the image).

## Requirements

- Docker and Docker Compose v2 (`docker compose`); tested on Linux only.
- The Ollama version also needs an NVIDIA graphics card, its driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). The 8B model needs about 8.5 GB of free graphics memory (see the project [README](../README.en.md#with-ollama)).

## The plain version (funscript-gen only)

All of the commands below run in the `docker/` folder:

```bash
cd docker
mkdir -p data videos                 # create them first, or Docker creates them as root and the container cannot write
docker compose up -d --build         # build and start in the background
```

Open http://127.0.0.1:7860 , and in the Settings tab enter the AI endpoint (for example `http://<vLLM host>:8000/v1`), the key and the model, then press "Save settings". The settings are kept in `data/.env` and used on later starts.

> When the endpoint is on the host itself (for example a vLLM running on the host), `127.0.0.1` inside the container means the container itself, not the host: enter the host's LAN IP.

Stopping and updating:

```bash
docker compose logs -f               # see the log
docker compose down                  # stop (the settings and outputs in data/ are kept)
git pull && docker compose up -d --build   # build again after updating the program
```

## The Ollama version (funscript-gen + Ollama)

```bash
cd docker
mkdir -p data videos
docker compose -f docker-compose.ollama.yaml up -d --build
```

On the first start `ollama-pull` downloads the model first (`qwen3-vl:8b-instruct` is about 6 GB), and funscript-gen starts only after the download; follow the progress with `docker compose -f docker-compose.ollama.yaml logs -f ollama-pull`. The model is kept in `ollama/` and is not downloaded again later.

On its first start funscript-gen creates `data/.env` with the backend set to Ollama and the endpoint to `http://ollama:11434`, so nothing needs to be entered in the Settings tab. Ollama's port is not published; only funscript-gen can reach it.

On an 8 GB graphics card use the 4B model instead (less accurate). `OLLAMA_MODEL` is written only when `data/.env` is first created; when it already exists, also change the model in the Settings tab to `qwen3-vl:4b-instruct`:

```bash
OLLAMA_MODEL=qwen3-vl:4b-instruct docker compose -f docker-compose.ollama.yaml up -d --build
```

## Variables that can be changed

Write them in `docker/.env` (read by docker compose automatically; this file is not the project's AI settings file `data/.env`), or put them before the command, for example `WEBUI_PORT=7861 docker compose up -d`:

| Variable | Default | Description |
|---|---|---|
| `WEBUI_BIND` | `127.0.0.1` | The address the web UI is open on; `0.0.0.0` lets other computers on the LAN connect. The web UI **has no login**: anyone who can reach it can use it and change the AI endpoint and key, so open it only on a trusted network |
| `WEBUI_PORT` | `7860` | The port on the host |
| `VIDEOS_DIR` | `./videos` | The folder mounted as `/videos` in the container (for the CLI) |
| `UID` / `GID` | `1000` | The container runs as this user, and the files in `data/` and `videos/` belong to it; when the host account is not 1000, set it to the values of `id -u` / `id -g` |
| `WITH_POSE` | `0` | `1`: the image also gets the CPU PyTorch and YOLO the skeleton mode (`--mode pose`) needs (about 0.8 GB more); add `--build` after changing it |
| `INIT_VLLM_BASE_URL` / `INIT_VLLM_API_KEY` / `INIT_VLLM_MODEL` | none | Plain version: the AI settings written when `data/.env` is first created (later use the Settings tab) |
| `OLLAMA_MODEL` | `qwen3-vl:8b-instruct` | Ollama version: the model downloaded, and also the model written when `data/.env` is first created |
| `OLLAMA_VERSION` | `0.40.13` | Ollama version: the version of the Ollama image |
| `FUNSCRIPT_GEN_LANG` | empty | The interface language (`zh-TW`, `en`, or the code of a pack in `data/lang/`); when empty, the language chosen in the web UI's Settings tab, and English if none was chosen (a container has no system language setting) |

## Using the CLI

Put the videos in `videos/` (or the folder `VIDEOS_DIR` names) and give commands inside the running container with `exec` (add `-f docker-compose.ollama.yaml` for the Ollama version); the arguments are the same as the project README's CLI:

```bash
docker compose exec funscript-gen funscript-gen generate /videos/a.mp4 --preset user   # writes videos/a.funscript
docker compose exec funscript-gen funscript-gen batch /videos
docker compose exec funscript-gen funscript-gen --help
```

When the web UI is not running, `run` executes once and ends (`entrypoint.sh` hands every command other than `webui` straight to `funscript-gen`):

```bash
docker compose run --rm funscript-gen generate /videos/a.mp4
```

## Where the data is kept

Only `/data` in the container needs to be kept, and it maps to `docker/data/` on the host:

| Location | Contents |
|---|---|
| `data/.env` | The AI settings (with the key, permission 600) |
| `data/.webui-last.json`, `data/.webui-cleanup.json` | The settings the web UI remembers (including the language) and the retention days of the outputs |
| `data/out/webui/` | The scripts the web UI made |
| `data/lang/` | Language packs you add yourself (`.toml`, optional; make the template with `docker compose exec funscript-gen funscript-gen lang template /data/lang/_template.toml`) |
| `data/.cache/funscript-gen/` | Cache of the AI's answers and the part boxes (can be deleted) |
| `data/.cache/huggingface/` | The part detection model (downloaded on first use, about 43 MB) |
| `data/tmp/` | Temporary files of videos uploaded to the web UI (not cleaned up automatically; can simply be deleted) |

`docker/data/`, `docker/videos/`, `docker/ollama/` and `docker/.env` are all listed in the project's `.gitignore`.

## Limitations

- **CPU only**: the image has no GPU OpenCL and no GPU build of onnxruntime, so optical flow and the part check run on the CPU (Auto under "Compute device" uses the CPU by itself; choosing GPU reports that no GPU was found and stops). In the Ollama version only Ollama uses the GPU.
- The skeleton mode needs a rebuild with `WITH_POSE=1`.

## When changing how it is built

When the way of installing changes (the dependencies or optional extras in `pyproject.toml`, a new system package, where the program writes files, the web UI's start arguments, etc.), check and update this folder's `Dockerfile`, the two compose files and this description together.
