# funscript-gen

[繁體中文](README.zh.md) | **English**

Analyses the motion between the people in a video and generates a `.funscript` script automatically.

It works as "the AI understands the picture, the computer measures the motion":
- A **vision-language model** (a vLLM or Ollama server you run yourself, Qwen3-VL-8B by default) decides which region of the picture each scene should look at, and whether anyone is in the picture.
- **Local computer vision** (optical flow) measures the displacement of the motion frame by frame, decides the high/low direction and writes the funscript.

It is currently tuned and validated for **anime** videos. This document describes the features, installation, usage and current limitations; to take part in development see [DEVELOPMENT.md](DEVELOPMENT.md) (in Traditional Chinese).

The documents and the interface use neutral terms for the tracked parts: the “active part” is the main object that moves back and forth in the picture, the “counterpart” is what it makes contact with, and the “target part / target region” is where the motion is measured.

The interface (CLI messages, web UI, desktop app) comes in Traditional Chinese and English, and any other language can be added as a language pack; see [Language](#language).

---

## Features

### Analysis

| Feature | Description |
|---|---|
| Scene splitting | Detects scene cuts and analyses each scene on its own; scenes longer than 20 s are split again |
| AI scene analysis | Calls a vision-language model (any OpenAI-compatible API, or Ollama) to decide the region to analyse in each scene; identical requests are cached, so running again does not wait for the AI |
| Candidate region check | On by default: several candidate regions are cropped into small images and the AI picks once more; the pick replaces the original region only if its motion is not weaker. One more AI call per scene |
| Hold at the top in scenes with nobody | On by default: intros, endings, black frames and other scenes with nobody in them output no motion and hold at the top of the output range |
| Stroke range check | On by default: the AI judges whether the tip and the whole of the active part can be seen; when the tip is not seen the scene's strokes are clipped to 80 (`--range-cap`). One more AI call per scene; the current models almost always answer "not seen" (see "Known issues") |
| Optical flow (default) | Finds the main back-and-forth motion inside the analysis region and subtracts the camera's own movement; needs no skeleton recognition, so it works on close-ups, first-person views, occluded views and animation |
| Hybrid (experimental) | `--focus hybrid`: also asks the AI to box the target region, and looks at that region when it is clearly visible. About twice the AI time |
| Skeleton mode | `--mode pose`: recognises both people's skeletons and measures distances between body parts; needs both people fully in frame, which anime almost never has. Needs a separate install (`./set-env.sh --pose`) |

### High/low direction

The motion in the picture first has to be assigned "which way is the push in". The default is "moving up = a higher position", but front-view and first-person shots are often upside down for a whole video, so there are these corrections:

| Feature | Description |
|---|---|
| Same direction across the chunks of a long shot | On by default: the 20 s chunks of one long shot use a consistent direction |
| Direction from the part boxes | On by default (`--no-part-sign` turns it off): a detection model made for anime finds the active part and the counterpart; apart = pulled back = high, and scenes that move against that are flipped automatically. Only works for scenes where both can be seen; the first use downloads a model of about 43 MB; on the CPU it adds about half to the processing time (a GPU can be used, see "Installation") |
| Direction from stroke speed | On by default (`--no-asym-sign` turns it off): the push in is usually fast and the pull back slow, so scenes that clearly rise faster than they fall are flipped automatically; the timing of impact sounds is also taken into account |
| Hints for possibly upside-down scenes | The summary and the scene table list scenes that may be upside down but were not flipped automatically; the preview shades them, and "Next to check" goes through them one by one |
| Manual flip | Flip the whole script with `--invert`; flip a single scene with "Flip" in the web UI's scene table or under the preview, or `--flip-scenes 0,3` on the CLI |

### Output

| Feature | Description |
|---|---|
| Rhythm filter | On by default: when the motion has a clear rhythm, drift and unrelated wobble are filtered out |
| Stroke size mode | Keep the size (default): the big motions of the whole video are full strokes and small motions give short strokes; fill the range: every stroke is full length |
| Shrinking at high frequency | Above 2 strokes per second the strokes get gradually shorter, and from 3 per second they shrink to 50% so the device can keep up (`--freq-limit 0` turns it off) |
| Rests and extra points | Off by default: keep the rests (`--dwell`), add points on slow long strokes (`--curve`), hold the position during pauses (`--hold`) |
| Bridging scene cuts | On by default: when the next scene does not continue the previous scene's rhythm at a cut, one repeat of the previous scene's motion is added so the cut does not stall or jerk (`--no-bridge` turns it off) |
| Keep the height of slow motion (experimental) | `--scene-center`: in scenes without a clear rhythm, slow large strokes also keep their height |
| Output settings | Output range (e.g. 40–90), stroke multiplier, maximum speed, minimum stroke size |

### Other

| Feature | Description |
|---|---|
| Web UI | Upload a video, adjust the settings, download the script, see the signal plot and the scene table; remembers the last settings, can cancel while running; the AI connection is set on the page; manages the files made before |
| Batch | Process several videos at once (the web UI's Batch tab, CLI `batch`); when one fails the next one continues; the CLI skips videos that already have a script, so running it again after an interruption carries on |
| Preview player | Like OpenFunscripter: position bar, an action timeline that scrolls with playback (the reference script can be overlaid), a speed heat map, keyboard control, slower/faster playback; draws the region analysed in each scene over the video; can flip a scene, enlarge or shrink one scene's strokes, set a scene's tops or bottoms to given positions, and edit actions directly |
| Presets | `--preset` and the web UI's "Preset": `default` is the default values, `user` is the author's web UI settings (Hybrid, keep rests, add points on long strokes), which score best in validation |
| Fast recompute | When only the output settings change for the same video, the last analysis is reused and the web UI finishes in about a second; on the CLI save the analysis with `generate --save-analysis` and recompute with other settings using `render` |
| Records how it was made | The output file records the program version, the AI model and all settings, so it can be reproduced |
| Comparison with hand-made scripts | With a reference script, `compare` or the web UI's reference script computes how well the turning points match (F1) and the correlation |
| Languages | Traditional Chinese and English; further languages are added as language packs (see [Language](#language)) |

The CLI and the web UI have exactly the same settings.

### Accuracy

On 38 anime videos that come with hand-made scripts, the turning-point match (F1, 1 = identical) averages about 0.72–0.79 per group. Short single-scene videos are almost the same as the hand-made script (0.90–0.99); long multi-scene videos are worse, mainly because the high/low direction is judged wrongly (see "Known issues"). For the detailed numbers see [DEVELOPMENT.md](DEVELOPMENT.md#目前的驗證結果).

---

## Installation

### Windows portable build

Download `FunscriptGen-<version>-win64.zip` from the [GitHub Releases page](https://github.com/yumeyis/funscript-gen/releases/latest) and extract it anywhere that can be written to (for example the desktop or `D:\`, not `C:\Program Files`); there is no need to install Python. Requires Windows 10 / 11, 64-bit.

- **Graphical interface**: double-click `FunscriptGen.exe`; it opens in a window of its own (using the system's WebView2; when that is missing it opens the default browser). It is used like the [web UI](#web-ui) below, and in addition "Choose…" picks a video on the computer directly (no upload). Closing the window ends the program.
- **Command line**: run `funscript-gen.exe` in the folder; the arguments are the same as the [CLI](#cli) below (replace `uv run funscript-gen` with `funscript-gen.exe`).
- Settings, caches and the graphical interface's output are all kept in `data\` in the folder and nothing is written to the user's folders; deleting the folder uninstalls it, and when updating, copy the old version's `data\` into the new one to keep the settings.
- The folder `lang\` beside the exe holds the language packs; see [Language](#language).
- With a graphics card, optical flow and part detection use the GPU automatically (OpenCL and DirectML). The skeleton mode is not included.
- The program is not digitally signed, so on the first run Windows may show "Windows protected your PC"; press "More info" → "Run anyway".

### Install from source

Requires Linux. Run `set-env.sh` once to finish the installation (it can be run again; finished steps are skipped):

```bash
./set-env.sh          # interactive: asks whether to install uv when it is missing, and asks for the AI API connection
./set-env.sh -y       # non-interactive: installs uv automatically, and only creates .env from the template when it is missing
./set-env.sh --test   # runs the unit tests after installing
./set-env.sh --pose   # also installs the PyTorch and YOLO the skeleton mode needs (about 0.8 GB)
```

It goes through: checking [uv](https://docs.astral.sh/uv/) (it can be installed automatically) → installing Python 3.12 and the pinned packages → creating `.env` → testing the AI API connection. It can also be installed by hand with `uv sync`.

> **With Docker**: when you do not want to install Python on the host, build an image from the files in [docker/](docker/README.md); `docker compose up -d --build` starts the web UI, and there is also a version that starts Ollama (Qwen3-VL) along with it (needs an NVIDIA graphics card). Inside the container optical flow and part detection run on the CPU only; see [docker/README.md](docker/README.md).

> **The skeleton mode** is optional (`uv sync --extra pose`, CPU PyTorch); once it is installed, `uv sync` also needs `--extra pose`, otherwise it is removed (`uv run` does not remove it). To run skeleton detection on an NVIDIA GPU, delete the two sections `[tool.uv.sources]` and `[[tool.uv.index]]` of `pyproject.toml` and run `uv sync --extra pose` again. The first use downloads a model of about 6 MB.

> **GPU acceleration**: three steps can use the GPU, optical flow, part detection and skeletons. The default is Auto (a GPU when one is usable, otherwise the CPU); in the web UI's Settings tab under "Compute device" or with the CLI's `--compute`, `--flow-compute` etc. it can be set to always use the GPU or the CPU. Optical flow uses the OpenCL built into the graphics driver, so nothing needs installing; the numbers computed on a GPU differ very slightly from the CPU's, so the same video can give slightly different scripts on a computer with and without a GPU; choose CPU for exactly the same result as the CPU's. The CLI prints the device actually used (`optical flow ran on …`, `part check ran on …`) and the web UI writes it in the result as "Compute device".

> **GPU acceleration for the part check**: on Windows the DirectML build is installed automatically (any GPU); on Linux the CPU build is installed by default; replace the non-Windows `onnxruntime` in `pyproject.toml` with `onnxruntime-gpu[cuda,cudnn]` (NVIDIA, another download of about 1 GB of CUDA libraries) and run `uv sync` again, and the program uses it automatically (about 4 times faster, the same result as the CPU); the CLI prints the device actually used (`part check ran on …`).

### Setting up the AI backend

vLLM is recommended (fast, and handles several requests at once); with only one graphics card, or for a simple installation, use [Ollama](#with-ollama).

#### With vLLM

Start vLLM on another host with a GPU (version 0.11 or later; the options below are for two 16 GB graphics cards):

```bash
vllm serve Qwen/Qwen3-VL-8B-Instruct \
  --tensor-parallel-size 2 \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.90 \
  --limit-mm-per-prompt '{"image": 8, "video": 0}' \
  --api-key <your own key> \
  --host 0.0.0.0 --port 8000
```

Then copy `.env.example` to `.env` and fill in the connection details. They can also be entered directly in the web UI's Settings tab; "Save settings" writes them to `.env`:

```ini
VLLM_BASE_URL=http://<host>:8000/v1
VLLM_API_KEY=<your own key>
VLLM_MODEL=Qwen/Qwen3-VL-8B-Instruct
# VLLM_BBOX_FORMAT=rel1000   # optional: rel1000 (Qwen3-VL etc.) or abs (Qwen2.5-VL); empty = decided by the model's name
# VLLM_CONCURRENCY=8         # optional: requests sent at once (default 8; vLLM batches them, 16 is about twice as fast again)
```

Other OpenAI-compatible endpoints also work, for example LM Studio and llama.cpp's `llama-server`, but only vLLM and Ollama have been tested. Qwen3-VL-8B is recommended; Qwen3-VL-30B-A3B did worse in tests. External commercial APIs (OpenAI, Gemini, etc.) mostly refuse to analyse adult images, and they need the pictures uploaded to a third party, so a model you run yourself is recommended.

#### With Ollama

Needs an Ollama that supports Qwen3-VL (0.40.13 was tested). Download the model on the host with the GPU; Ollama accepts only local connections by default, so to use it from another computer set the environment variable `OLLAMA_HOST=0.0.0.0` before starting it:

```bash
ollama pull qwen3-vl:8b-instruct
```

`.env` (or choose "Ollama" for "Backend" in the web UI's Settings tab):

```ini
VLLM_BACKEND=ollama
VLLM_BASE_URL=http://<host>:11434
VLLM_MODEL=qwen3-vl:8b-instruct
# VLLM_NUM_CTX=16384         # optional: the context length of each request
```

- **One-click run**: after choosing "Ollama" for "Backend" in the web UI's Settings tab, a "one-click run" section appears: choose Docker (a container is created for you) or the installed Ollama, choose the model, and "Run and configure" starts Ollama, downloads the model and saves the endpoint and model into the settings (the saved API key is kept). The Ollama it started is stopped when the program ends. "Check status" shows what is running; "Remove the auto-installed Ollama" deletes the Docker container, model volume and image (an installed Ollama is not affected). The GPU in Docker mode needs the NVIDIA Container Toolkit; without it a CPU-only container is used (very slow). This has not been tested in every environment.
- Use the "Ollama" backend, and do not treat Ollama's `/v1` as an OpenAI-compatible endpoint: `/v1` uses Ollama's default context length, so sending 4 images at once is refused, and the description text before the images goes out of place.
- Graphics memory: the 8B model takes about 5.9 GB, and with the context about 8.5 GB of memory is needed. When it does not fit, Ollama puts part of it on the CPU and a request takes minutes; on an 8 GB graphics card use `qwen3-vl:4b-instruct` instead (about 3.2 GB, less accurate).
- Ollama handles only one request at a time (the server's `OLLAMA_NUM_PARALLEL` can be raised, but each one needs memory for a context), so the AI analysis is slower than with vLLM.

---

## Usage

### Web UI

```bash
./start-webui.sh                           # local only by default: http://127.0.0.1:7860
WEBUI_PORT=7861 ./start-webui.sh           # override a setting temporarily with an environment variable
```

The server settings are in the "settings" block at the top of `start-webui.sh`:

| Setting | Default | Description |
|---|---|---|
| `WEBUI_HOST` | `127.0.0.1` | Address to listen on; `0.0.0.0` lets other computers on the LAN connect |
| `WEBUI_PORT` | `7860` | Port |
| `WEBUI_OUTPUT_DIR` | `out/webui` | Where the generated funscripts are kept |

- Order of precedence: environment variable > `start-webui.local.sh` > the default in the script. Settings that belong to this computer only can go in `start-webui.local.sh` (listed in `.gitignore`), for example `WEBUI_HOST=0.0.0.0`.
- The web UI is designed for **one user and has no login**. When it is opened to the LAN (not `127.0.0.1`) the script shows a warning: anyone who can reach this computer can use it, and can change the AI endpoint and key.
- When the port is taken the script says which program holds it. The AI API settings go in `.env` or the web UI's Settings tab.
- It can also be run directly: `uv run funscript-gen webui --host … --port … --output-dir …`.
- **Desktop mode**: `uv run funscript-gen app` opens on this computer only (it picks a free port by itself; `--ui browser` uses the browser instead), takes the path of a video on the computer directly, and can save the script beside the video (see step 2 below). A window of its own needs the optional package `uv sync --extra gui` (pywebview); without it the browser opens. The Windows portable build's `FunscriptGen.exe` is this mode.

Steps:

1. On first use, check the AI API in the Settings tab (the AI API, Compute device and Output files sections of the Settings tab can be collapsed): enter the endpoint URL and key, press "Get model list" to choose the model, then "Save settings".
2. Upload a video in the Generate tab. In desktop mode (`funscript-gen app`, the Windows build's `FunscriptGen.exe`) a path can also be entered under "Or a video on this computer", or press "Choose…", to read the original file directly; the Batch tab likewise takes several videos or folders. For videos chosen on this computer, tick "Also save the script beside the video" under "Output files" in the Settings tab and the script is saved as a `.funscript` with the video's name (a copy stays in the output folder; a script of the same name beside the video that funscript-gen did not make is never overwritten).
3. Adjust the settings. First choose one under "Preset" and press "Apply"; each can still be adjusted afterwards. Leave the items marked "AI decides" empty. To score against a hand-made script, turn on "Use a reference script" under "Advanced", and an upload box appears. Whether the GPU or the CPU computes is set under "Compute device (GPU / CPU)" in the Settings tab (Auto / GPU / CPU, for everything or per step, Auto by default; changes are remembered at once, and neither the presets nor "Restore default settings" touch them).
4. Press "Generate funscript" at the top of the left column ("Cancel" next to it stops a run in progress), then download the script and look at the signal plot and the scene analysis table. Pressing Generate again for the same video after changing only the output settings reuses the last analysis and takes about a second; the video is analysed again only when an analysis setting (the AI, the analysis target, the optical flow width, the frame rate, the scene cut sensitivity, part boxes, etc.) or the AI endpoint changes. The Generate tab's settings are remembered when you press it (kept in `.webui-last.json`) and applied when the page is opened again; "Restore default settings" goes back to the defaults.
5. The **preview player** on the right loads the video and the script just made, to check while playing; with a reference script it is overlaid as a grey line. "Scene" in the info bar is the number of the scene at the current playback position (the same as `#` in the scene table). The box on the video is the region in which this scene's motion was analysed (tick "Analysis region" or press `R` to show or hide it): the solid one is the region in use, and the hybrid mode's other region is dashed; the info bar says which one is in use, and without a box it is the whole picture. When the output does not match the picture, first look at whether the box is where the motion is.
6. **When it is upside down**: when the preview plays that scene, press "Flip" under the player, or click that scene's "Flip" column (`⇅`) in the scene analysis table. The scene is flipped at once and the output file is updated too; press again to restore it, and the summary lists the matching CLI option (`--flip-scenes …`). "Possibly upside down" in the summary lists the scenes worth checking first, which the preview's timeline shades yellow; press "Next to check" in the info bar (or `N`) to jump to the next one and play it, and press "Flip" if it is upside down.
7. **Editing single actions**: tick "Edit" in the player (or press `E`), and the keys for editing are listed under the player: drag actions on the timeline (left/right changes the time, up/down the position), drag on empty space with the left button held to select several (`Shift` adds to the selection); selected points can be dragged together, adjusted with `↑` `↓` or deleted, `A` adds one at the playback position (or double-click empty space), `Delete` deletes, `↑` `↓` change the position (or hold and drag on the position bar on the right, and the video jumps to that action), `Ctrl+Z` undoes, and when done press "Save edits" under the player to write the output file. When a scene's strokes are too small or too large, play to that scene and press `+` to enlarge or `-` to shrink (the "Size" button in the info bar works too; each press is ×1.25 or ×0.8, every stroke around its own midpoint, so motion that goes up and down is not pushed to the top or bottom). To make every stroke of a scene reach the same height, enter a position (0–100) under "Top" or "Bottom" in the info bar and press "Set" or `Enter`: the action at every peak (or valley) of the scene is set to that position and the points between move in proportion (the player remembers the number entered). With several points selected while editing, size and top/bottom change only the selected points. Pressing "Flip" (under the player or in the scene table) keeps edits that are not saved yet; an edited output file is marked `hand_edited` in its metadata (the CLI cannot reproduce these changes).
8. **Several videos at once**: in the Batch tab choose several videos and press "Start batch"; they are processed one after another with the Generate tab's current settings, all into the same `out/webui/<time>/` folder. The result table lists each video's status, number of scenes, number of actions and the scenes that may be upside down; when one fails the reason is noted and the next one continues, and "Cancel" stops at the current one (finished ones are kept). To check, flip or edit one, select it under "Finished videos" and press "Open in the Generate tab"; it can then be previewed, flipped and edited just like one made in the Generate tab, and pressing Generate there after changing only the output settings reuses its analysis too.
9. The Output tab can download the scripts made before again, or clear them all.
10. **The Preview tab** loads any video and funscript (for example a script from another tool or another person) to preview, edit and flip scenes on its own. In the video box the file dialog can pick a video and a funscript together (for example hold Ctrl and click two files) and they go into the two boxes; they can also be uploaded separately as before. Scenes are split automatically when loading and listed in the scene table below (start and end time, cut strength, number of actions); click the "Flip" column to flip a scene. When scenes are cut too finely or missed, adjust this tab's "Scene cut sensitivity" (lower cuts more easily; when the page opens it follows the Generate tab's setting), and release the slider or press "Split scenes again" to recompute at once, with no reload; the message lists the number of scenes when the sensitivity goes either way, and the scene table also marks where the cut strength is close to the threshold. When scenes are split again, earlier flips stay in the script, and edits that are not saved yet are saved first. A load that takes long can be stopped with "Cancel loading"; "Preview without scene cuts" skips scene detection and treats the whole video as one scene. Progress while loading updates once per percent.

The generated scripts are kept in `out/webui/<time>/` (`data\out\<time>\` in the Windows portable build), named like the video (only characters a file name does not allow are replaced with underscores), so players can pair them automatically. "Retention days" in the Settings tab deletes expired outputs automatically (only folders named by time are deleted); the CLI can also clean up:

```bash
uv run funscript-gen clean-webui                       # delete by the retention days set in the web UI
uv run funscript-gen clean-webui --older-than-days 7   # delete those older than 7 days
uv run funscript-gen clean-webui --all                 # delete everything
```

Preview player controls:

| Control | Function |
|---|---|
| Click the timeline / heat map | Jump to that time |
| Scroll the mouse wheel over the timeline | Zoom the time range shown (2–120 s) |
| Hold the right button and drag on the timeline | Scroll the timeline (drag right to see earlier, left to see later; the playing state returns when released) |
| `Space` | Play / pause |
| `←` `→` | Jump to the previous / next action |
| `Shift` + `←` `→` | 5 seconds back / forward |
| `,` `.` | One frame back / forward |
| `[` `]` | Slower / faster playback (0.25–2×, kept the next time the player opens) |
| `PageUp` `PageDown` | Jump to the start of the previous / next scene (the "Previous scene" "Next scene" buttons in the info bar work too) |
| `N` | Jump to the next scene to check (possibly upside down) and play it |
| `E` | Editing on / off (the timeline gets a frame and the keys for editing are listed below); while editing: drag an action to move it, drag on empty space to select several (`Shift`+click or drag adds to the selection; selected points move, adjust or delete together), `A` or `Insert` adds one at the playback position (or double-click empty space), `Delete` or `Backspace` deletes the selected points, `↑` `↓` change the position ±5 (with `Shift` ±1; or hold and drag on the position bar on the right), `Ctrl+Z` undoes, `Esc` deselects, `←` `→` jump to and select the previous / next action |
| `-` `+` | Shrink / enlarge the strokes of the current scene (the selected points when several are selected) (×0.8 / ×1.25 each time, every stroke around its own midpoint; turns editing on, and "Save edits" must be pressed) |
| "Top" "Bottom" + "Set" or `Enter` | Set the action at every peak / valley of the current scene (the selected points when several are selected) to the position entered, and the points between move in proportion (turns editing on, and "Save edits" must be pressed) |
| `R` | Show / hide the analysis region (in the Generate tab's preview; a script loaded in the Preview tab has no analysis data and shows none) |

The keyboard needs the player to be clicked once first. The colours of the heat map stand for speed: blue is slow, red is fast.

### CLI

```bash
# Generate a script (output <video>.funscript by default)
uv run funscript-gen generate video.mp4

# Presets: user = the author's web UI settings (best validation scores); the arguments after it override the preset
uv run funscript-gen generate video.mp4 --preset user
uv run funscript-gen generate video.mp4 --preset user --no-curve

# Output range 40–90, and also save debug data and a signal plot
uv run funscript-gen generate video.mp4 --range-low 40 --range-high 90 --debug

# Keep the rests at turning points, and add points on slower long strokes
uv run funscript-gen generate video.mp4 --dwell --curve

# Turn off the direction checks from part boxes and stroke speed (faster; the part detection adds about half the time on the CPU)
uv run funscript-gen generate video.mp4 --no-part-sign --no-asym-sign

# Save the analysis, then recompute with other output settings (no decoding or AI calls again; changing an analysis setting is refused)
uv run funscript-gen generate video.mp4 --save-analysis video.analysis.pkl
uv run funscript-gen render video.analysis.pkl -o video-40-90.funscript --range-low 40 --range-high 90

# Faster: optical flow on a 320-wide picture (about twice as fast, see the speed under "Known issues")
uv run funscript-gen generate video.mp4 --flow-width 320

# Override the AI's decisions by hand
uv run funscript-gen generate video.mp4 --mode flow --axis vertical --roi 0.3,0.4,0.7,0.8

# Several videos or a whole folder (-r includes subfolders): scripts are written beside each video, and videos that already have one are skipped
uv run funscript-gen batch ~/videos --preset user
uv run funscript-gen batch a.mp4 b.mkv ~/videos -r -o ~/scripts --overwrite   # all written to ~/scripts, those that exist are redone

# Compare with a hand-made script
uv run funscript-gen compare reference.funscript video.funscript

# Send a few frames to the AI and see what it decides (writes an image with the regions marked, out/ai-check.jpg)
uv run funscript-gen ai-check video.mp4 --at 60

# Video information
uv run funscript-gen info video.mp4

# The language of the messages (see "Language"), and the language packs
uv run funscript-gen --lang en generate video.mp4
uv run funscript-gen lang list
```

`uv run funscript-gen <command> --help` shows all arguments and their defaults. The settings of `batch` are the same as `generate`'s (except `--flip-scenes`: the scene numbers differ for each video, so to flip, run `generate` for that one separately); videos are found by extension (mp4, mkv, webm, mov, avi, etc.); after an interruption (`Ctrl+C`), running the same command again carries on with the videos that have no script yet, and with a failed video the exit code is 1.

#### Main arguments

| Argument | Default | Description |
|---|---|---|
| `--preset` | none | Start from a preset (`default`, `user`); the other arguments override the preset's values |
| `--save-analysis` | none | Also save the analysis to a file, for `render` to recompute with other output settings |
| `--ai/--no-ai` | on | Whether the AI analyses each scene (when off, the whole picture is analysed) |
| `--mode` | `auto` | `auto` (the same as flow) / `flow` / `pose` (skeletons, needs `uv sync --extra pose`) |
| `--focus` | `general` | `general` (the motion between the two people) / `hybrid` (also a target-region analysis, chosen per frame, experimental) |
| `--region-pick/--no-region-pick` | on | Let the AI pick the analysis region from candidates once more (general mode; not done when `--roi` is given) |
| `--contact-pick/--no-contact-pick` | on | Hybrid: when the AI thinks the contact part is most likely the hand and the mouth, follow the one that moves more (needs vLLM; not done on Ollama); `--contact-min-prob` (0.1) is the second one's minimum probability, below which they are not compared |
| `--stroke-range/--no-stroke-range` | on | Stroke range check; `--range-cap` (80) and `--range-floor` (20) are its limits |
| `--rest-empty/--no-rest-empty` | on | Scenes in which the AI sees nobody hold at the top |
| `--axis` / `--roi` | AI decides | Motion axis (`vertical` etc.) / analysis region `x1,y1,x2,y2` (0–1) |
| `--ref-a` / `--ref-b` | AI decides | The body parts the skeleton mode uses: `head` `shoulder` `wrist` `hip` `knee` `ankle` `torso` |
| `--chunk-align/--no-chunk-align` | on | The 20 s chunks of a long shot use a consistent stroke direction |
| `--part-sign/--no-part-sign` | on | Direction from the part boxes; a smaller `--part-sign-threshold` (0.2) flips more easily |
| `--asym-sign/--no-asym-sign` | on | Direction from stroke speed; `--asym-threshold` (0.5), `--asym-audio` (on), `--asym-audio-threshold` (0.2) |
| `--sound-hint` | off | Scenes whose sound onsets fall at the highs but were not flipped are listed as "possibly upside down" (mostly false alarms on new videos) |
| `--invert` | off | Flip upside down within the output range |
| `--flip-scenes` | none | Flip only these scenes, e.g. `0,3` (the numbers are in the scenes listed after generating, and the web UI's scene table) |
| `--range-low` / `--range-high` | 0 / 100 | The range of the output positions |
| `--amplitude` / `--gain` | `preserve` / 1.0 | Stroke size mode (`preserve` / `fill`) and the stroke multiplier of the keep-size mode |
| `--rhythm-filter/--no-rhythm-filter` | on | Rhythm filter (optical flow only) |
| `--max-speed` | 500 | Maximum speed (position units / s); the default is for an ordinary-servo OSR2, and with better servos it can be raised to 600 |
| `--freq-limit` / `--freq-max` / `--freq-min-scale` | 2.0 / 3.0 / 0.5 | Shrinking at high frequency: the frequency where shrinking starts, the frequency where it is smallest (Hz) and the smallest stroke ratio; `--freq-limit 0` turns it off |
| `--min-prominence` | 0.15 | Minimum stroke size (fraction of the local range); larger ignores small motion |
| `--dwell` / `--dwell-tol` / `--dwell-min-ms` | off / 0.05 / 200 | Keep the rests at turning points |
| `--hold` / `--hold-after-ms` | off / 1000 | Hold during pauses (the gap is also used to tell pauses in the high-frequency shrinking) |
| `--curve` / `--curve-after-ms` / `--curve-tol` | off / 600 / 5 | Add points on long strokes |
| `--bridge/--no-bridge` | on | Copy one stroke of the previous scene when the rhythm does not continue at a cut |
| `--scene-center/--no-scene-center` | off | Experimental: scenes without a clear rhythm are placed by the whole scene's range |
| `--fps` / `--scene-threshold` | 30 / 30 | Analysis frame rate; scene cut sensitivity (lower cuts more easily) |
| `--flow-width` | 480 | The picture width of the optical flow computation (160–480); a portrait video narrower than this is not enlarged |
| `--flow-workers` / `--ai-workers` | half the CPU cores / 8 from `.env` | Optical flow jobs at the same time (each up to 5 s, the output does not change) / AI requests sent at once |
| `--compute` | `auto` | Compute on the GPU or the CPU: `auto` (a GPU when one is usable, otherwise the CPU) / `gpu` (when no usable GPU is found, say why and stop) / `cpu` |
| `--flow-compute` / `--part-compute` / `--pose-compute` | `auto` | GPU or CPU for optical flow, part detection and skeletons separately; `auto` follows `--compute` |
| `--debug` | off | Also write `.debug.json` and `.debug.png` |

Caches: the AI's answers are kept in `~/.cache/funscript-gen/ai/` and the part boxes in `~/.cache/funscript-gen/parts/`; both can simply be deleted (they are computed again next time).

### Language

The CLI messages, the web UI, the desktop app and the preview player come in Traditional Chinese (`zh-TW`) and English (`en`). Every text lives in a **language pack**, a `.toml` file named after the language code in the `lang` folder:

- **Choosing the language**: in the web UI (and the desktop app) the "語言 / Language" list at the top of the Settings tab; it takes effect at once, without a reload, and is remembered. On the CLI use `--lang en` (e.g. `funscript-gen --lang en generate video.mp4`) or the environment variable `FUNSCRIPT_GEN_LANG`. When nothing is chosen the system's language is used (English when there is no pack for it).
- **Where the packs are**: `lang/` in the program's folder (the Windows portable build: `lang\` beside `FunscriptGen.exe`; with Docker: `lang/` in the data folder), plus the packs built into the program. A file with the same code in `lang/` replaces the built-in pack. `funscript-gen lang list` lists the packs found.
- **Adding a language**: copy `lang/_template.toml` to `lang/<code>.toml` (for example `ja.toml`), fill in `code` and `name` (the language's own name, shown in the list) and write each text after its key. The comment lines above each key show the Traditional Chinese and English texts. A text left empty falls back to Traditional Chinese. Keep the `{placeholders}` and the Markdown / `<k>…</k>` markers, then check the file with `funscript-gen lang check lang/<code>.toml`. Press reload in the web UI and the new language is in the list.
- The text of an analysis note (for example "Region choice failed" in the scene table) is written in the language in use when the video is analysed; it does not change afterwards.

---

## Known issues and limitations

**High/low direction**
- **Front-view and first-person videos are often upside down for a whole video**: in such pictures moving up is the push in, while in a first-person top view it also moves up but is the pull back, and optical flow cannot tell them apart. The part boxes and the stroke speed check, both on by default, correct some of them; for the rest use the "possibly upside down" hints and the preview, `--invert` for a whole video that is upside down, and "Flip" for single scenes.
- **The direction of heavily cut videos is often wrong**: when every scene is only a second or two (for example some 3D animation) there is not enough information to judge the direction, which amounts to guessing.
- **The part boxes only work for scenes where the active part and the counterpart can be seen** (mouth contact, hand contact and rear view are not affected), and have been validated on anime only.
- **The "possibly upside down" hints from the sound (`--sound-hint`) are mostly false alarms on new videos**, so they are off by default.

**Accuracy**
- **The accuracy of long videos is clearly lower than of short ones**, and the depth of each stroke often differs from the hand-made script.
- **Scenes in which someone is in the picture but still keep outputting motion**; only scenes with nobody in them hold still.
- **Small motion on top of slow large motion is not caught.**
- **The AI's judgement in the stroke range check is almost always "tip not seen"**, which amounts to setting every scene's upper limit to 80; for full strokes turn it off with `--no-stroke-range`.
- **Shrinking at high frequency is more conservative than hand-made scripts**: hand-made scripts shorten clearly only at 4 strokes per second; use `--freq-limit 0` when it is not wanted.
- **Bridging scene cuts** adds one extra stroke when the original stops or slows at the cut; use `--no-bridge` when it is not wanted.
- **The candidate region check sometimes switches to a worse region.**
- **Each scene (or 20 s chunk) uses one fixed analysis region**: when the subject moves a lot or the camera pans, the subject may leave the region. The preview shows the region analysed in each scene.
- **Optical flow cannot follow pictures without texture** (a plain background); large plain areas in animation may have a similar problem (not verified).
- **Full strokes are set by the big motions of the whole video**: when the whole video has only small motion, use `--gain` to make it smaller.
- **Only a single main axis is output**, not a multi-axis script.
- **Scene splitting only detects hard cuts**; fades and dissolves may not be detected, and a long shot's chunk boundaries may have fewer actions.

**AI**
- **Running the same video again may give slightly different results**: the AI's answers can differ when several requests are handled at once (answers are cached, so they are the same from the second time).
- **When the AI refuses or the connection fails** the whole picture is analysed instead, and the accuracy may drop.
- **Hybrid is only slightly better than the general mode**, but takes about twice the AI time.
- **Following the one that moves more when the hand and the mouth both touch** (`--contact-pick`) is on the whole a tie, and a few scenes get worse; when a scene seems to follow the wrong one, generate again with `--no-contact-pick` and compare.
- **The check for minors currently has no effect**; it does not skip any scene.

**Speed**
- A 2-minute video with 16 scenes takes about 23 s on a 12-core CPU (AI already cached, without the part check); without the cache the AI analysis takes about 30 s, running at the same time as the optical flow. A short video with only one or two scenes is also cut into small pieces and computed in parallel.
- The part check is very slow on the CPU (for a 3-minute video the time almost doubles) and its result is cached; a GPU can be used instead (see "Installation"), and when in a hurry turn it off with `--no-part-sign`.
- `--flow-width 320` is about twice as fast, but a video whose direction is unclear may change direction, so the default is 480.
- A computer with a GPU (OpenCL) computes optical flow on the GPU by default, and the script differs very slightly from one made on the CPU only; for exactly the same result as the CPU's, set optical flow to CPU under "Compute device" in the Settings tab.

**Web UI**
- Only one job is processed at a time; other requests wait in line.
- It is designed for one user and **has no login**; when it is opened to the LAN, anyone who can open the web UI can use it and can change the AI endpoint and key in the Settings tab (the key is never shown on the page, but it can be overwritten). Open it only on a trusted network.
- The AI settings, the remembered settings, the language and the retention days are kept on the server and shared by all browser tabs; options that no longer exist after an update, or numbers out of range, fall back to the defaults.
- The temporary files of uploaded videos are not cleaned up automatically; when "Clear all" clears the outputs, a script that was just made and not downloaded yet is deleted too.
- When a download link is clicked in the window of the desktop mode (the Windows build's `FunscriptGen.exe`), the file goes to the user's "Downloads" folder; to keep it beside the video use the option in the Settings tab, or "Open the output folder" in the Output tab.
- "Cancel" stops at the next progress update (during the AI analysis, after the next answer comes back).
- The preview player only supports formats the browser can play (H.264 MP4 is recommended); a preview's link stops working after the server restarts. After editing actions press "Save edits": when generating again, edits that are not saved yet are lost ("Flip" keeps them).
- Generating again from the last analysis does not keep the scenes flipped by hand the last time.
- The player's own texts, and the analysis notes in the scene table, are made when the preview or the analysis is made, so after the language is changed they stay in the old language until the next one.

**Other**
- The rotation information of videos is not handled (a portrait video from a phone may be treated as a landscape picture).

---

## Usage notice and disclaimer

- **Legal use and copyright**: Please only process videos that you have a legal right to use. You are solely responsible for ensuring that the videos you process and the `.funscript` files you generate comply with applicable laws and copyright regulations.
- **Age and content restriction (18+)**: This tool is designed for analysing motion in adult anime videos and is intended solely for adults of legal age in their jurisdiction. Using this tool on any unlawful content (including, without limitation, any content involving minors or non-consensual imagery) is **strictly prohibited**.
- **Hardware safety disclaimer**: Automatically generated `.funscript` files may contain fast movements or inverted directions. If you use generated scripts to drive any physical actuator or motorized device, always inspect the script in the preview player or your control software first and configure safe stroke limits and speed caps. This software is provided **"AS IS"**, without warranty of any kind, express or implied; the authors and contributors shall not be liable for any hardware damage, data loss or personal injury arising from the use of this software or its outputs.
- **Privacy and data flow**: This program collects no telemetry. Video decoding, optical flow and part detection all run locally on your machine; only sampled scene keyframes are sent to the AI endpoint you configure. Please use a self-hosted local or LAN server (vLLM or Ollama) and do not send private or copyrighted imagery to third-party commercial APIs.

## References and acknowledgements

- **Anime part detection model and preprocessing**: The part-box direction check (`--part-sign`) downloads DeepGHS's [`deepghs/anime_censor_detection`](https://huggingface.co/deepghs/anime_censor_detection) model from Hugging Face on first use (the model is not distributed in this repository); the YOLOv8 ONNX preprocessing and box decoding in `src/funscript_gen/tracking/parts.py` follow [`dghs-imgutils`](https://github.com/deepghs/imgutils) (MIT License).
- **Vision-language model and inference servers**: Defaults to the Qwen team's [`Qwen/Qwen3-VL-8B-Instruct`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) (Apache-2.0), served via [vLLM](https://github.com/vllm-project/vllm) or [Ollama](https://github.com/ollama/ollama).
- **Preview player inspiration**: The preview player's position bar, scrolling action timeline, speed heat map and keyboard controls were inspired by [OpenFunscripter (OFS)](https://github.com/OpenFunscripter/OFS).
- **Core open-source libraries**: Video decoding uses [PyAV](https://github.com/PyAV-Org/PyAV) (FFmpeg), optical flow and image processing use [OpenCV](https://opencv.org/), signal processing uses [NumPy](https://numpy.org/) and [SciPy](https://scipy.org/), part inference uses [ONNX Runtime](https://onnxruntime.ai/), the web UI and desktop window use [Gradio](https://www.gradio.app/) and [pywebview](https://pywebview.flowrl.com/), and the optional skeleton mode (`--extra pose`) uses [Ultralytics YOLO11-pose](https://github.com/ultralytics/ultralytics).

## Developed with Claude

This project was developed with Anthropic's **Claude (Claude Code)** across system architecture design, computer-vision and signal-processing experiments, CLI / Web UI / desktop app and preview player implementation, automated tests, internationalisation and documentation. See [DEVELOPMENT.md](DEVELOPMENT.md) and [PLAN.md](PLAN.md) for the architecture and full experiment logs.

## License

This project's source code is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) (source-available, **not** open source as the OSI defines it):

- **Allowed**: personal use, research, hobby and education, and other noncommercial uses such as by nonprofits, educational institutions, charities and government bodies; you may modify and distribute it, but when distributing you must include the license terms and the copyright notice (`Required Notice`).
- **Commercial use is prohibited**: you may not use the software for a commercial purpose, for example as part of a paid product or service, selling it, or generating scripts for a fee. For commercial use, ask the author for a separate license (open an issue on GitHub).
- **Output files**: the `.funscript` files you generate with this software are yours; the license limits the software only. The rights in the videos, hand-made scripts and other material you generated them from still belong to their authors; see "Legal use and copyright" above.
- The license covers only this project's own code. Third-party packages and models are under their own licenses (some allow commercial use, some do not or only on conditions, for example the optional AGPL-3.0 package `ultralytics` and the models downloaded at runtime); check them before use.

Third-party open-source packages, components bundled in the Windows portable build, and external models downloaded at runtime (including the optional `--extra pose` dependency `ultralytics` under AGPL-3.0) remain under their respective licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.
