# Third-Party Notices / 第三方軟體與模型授權聲明

`funscript-gen` is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) (no commercial use). It uses or interacts with third-party open-source packages and machine-learning models listed below. Each third-party component remains under its own license.

`funscript-gen` 本身採用 [PolyForm Noncommercial License 1.0.0](LICENSE) 授權（禁止商業使用）。本專案使用或參考了以下第三方開源套件與模型，各元件仍依其原本的授權條款釋出。

---

## 1. Referenced Code / 參考程式碼

### dghs-imgutils (`deepghs/imgutils`)
- **Repository**: https://github.com/deepghs/imgutils
- **License**: MIT License (`Copyright (c) 2022 DeepGHS`)
- **License text**: the MIT License; this notice and the copyright line above are kept as the license requires. The part of the code it covers stays under it, whatever license the rest of this project uses.
- **Usage in this project**: The YOLOv8 ONNX preprocessing and bounding-box decoding logic in `src/funscript_gen/tracking/parts.py` follows `imgutils.detect.yolo` so that `anime_censor_detection` can run directly on `onnxruntime` without pinning `numpy` or `opencv-python`.

<details><summary>MIT License text (dghs-imgutils)</summary>

```
MIT License

Copyright (c) 2022 DeepGHS

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

</details>

---

## 2. External Models (Downloaded at Runtime, Not Distributed in Repo or Releases) / 執行時下載之外部模型（未包含於儲存庫或發行包中）

1. **`deepghs/anime_censor_detection` (`censor_detect_v1.0_s/model.onnx`)**
   - **Source**: https://huggingface.co/deepghs/anime_censor_detection
   - **Usage**: Downloaded on first use via `huggingface-hub` when `--part-sign` (default on) is enabled. Subject to the model repository's terms and YOLOv8 licensing terms.
2. **`Qwen/Qwen3-VL-8B-Instruct` (or user-selected VLM)**
   - **Source**: https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct
   - **License**: Apache License 2.0
   - **Usage**: Hosted separately by the user on a vLLM or Ollama server (`docker-compose.ollama.yaml` pulls `qwen3-vl` via Ollama on first start).
3. **`deepghs/nudenet_onnx` (`320n.onnx`) — development scripts only**
   - **Source**: https://huggingface.co/deepghs/nudenet_onnx
   - **Usage**: Downloaded only by `scripts/experiments/part_detectors.py`, an experiment script that is not part of the program, the Windows portable build or the Docker image. NudeNet itself is published under AGPL-3.0; check the model repository's terms before use.
4. **`Ultralytics YOLO11-pose` (`yolo11n-pose.pt`) — Optional**
   - **Source**: https://github.com/ultralytics/ultralytics
   - **License**: GNU Affero General Public License v3.0 (AGPL-3.0)
   - **Usage**: Used only when the user explicitly installs the optional `pose` extra (`uv sync --extra pose`) and runs `--mode pose`. Not installed by default and not included in the Windows portable build.

---

## 3. Python Dependencies & Portable Build Components / 相依套件與 Windows 免安裝版內附元件

The Windows portable archive (`FunscriptGen-<version>-win64.zip`) and Docker image bundle a standalone Python runtime and pre-built Python wheels from `uv.lock`. Their license files are preserved inside `runtime/Lib/site-packages/*.dist-info/` (Windows build) or `/opt/venv/lib/python3.12/site-packages/*.dist-info/` (Docker image):

| Component / Package | License | URL |
|---|---|---|
| Python (`python-build-standalone`) | PSF-2.0 / BSD-3-Clause | https://github.com/astral-sh/python-build-standalone |
| `av` (PyAV, bundles FFmpeg libraries) | BSD-3-Clause (FFmpeg: LGPLv2.1+ / GPLv2+) | https://github.com/PyAV-Org/PyAV |
| `numpy` | BSD-3-Clause | https://numpy.org/ |
| `scipy` | BSD-3-Clause | https://scipy.org/ |
| `opencv-python` | Apache-2.0 | https://github.com/opencv/opencv-python |
| `matplotlib` | PSF-based (Matplotlib License) | https://matplotlib.org/ |
| `pillow` | MIT-CMU | https://python-pillow.org/ |
| `typer` | MIT | https://typer.tiangolo.com/ |
| `pydantic` / `pydantic-settings` | MIT | https://docs.pydantic.dev/ |
| `openai` (Python SDK) | Apache-2.0 | https://github.com/openai/openai-python |
| `gradio` | Apache-2.0 | https://www.gradio.app/ |
| `onnxruntime` / `onnxruntime-directml` | MIT | https://onnxruntime.ai/ |
| `huggingface-hub` | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| `pywebview` (optional `gui` extra, in Windows build) | BSD-3-Clause | https://pywebview.flowrl.com/ |
| `ultralytics` (optional `pose` extra, not in Windows build) | AGPL-3.0 | https://github.com/ultralytics/ultralytics |
| `torch` / `torchvision` (optional `pose` extra) | BSD-3-Clause | https://pytorch.org/ |
| `lap` (optional `pose` extra) | BSD-2-Clause | https://github.com/gatagat/lap |

---

## 4. Notes for redistribution and commercial use / 散布與商業使用的注意事項

- This project's own code is **not for commercial use** (PolyForm Noncommercial 1.0.0). Third-party components are not made noncommercial by that, nor commercial: each keeps its own terms, and some (for example the models downloaded at runtime, and AGPL-3.0 `ultralytics`) may not allow commercial use or have other conditions. Check each license yourself.
- When you pass on the Windows portable build or the Docker image, you pass on the third-party components in it: keep this file and the license files of those components with it.
- The models listed in section 2 are not distributed with this project. Their terms are those of their own repositories at the time you download them; the statements above are a summary and were not re-verified against each repository's current terms.

本專案自己的程式碼**禁止商業使用**（PolyForm Noncommercial 1.0.0），但這不會改變第三方元件的授權：各元件仍依自己的條款，有些（例如執行時下載的模型、AGPL-3.0 的 `ultralytics`）可能不允許商業使用或有其他條件，請自行確認。轉交 Windows 免安裝版或 Docker 映像時，其中的第三方元件一併轉交，請附上本檔與各元件的授權檔。第 2 節的模型不隨本專案散布，條款以下載當時各模型頁面為準；上面的敘述是摘要，未逐一重新對照各頁面的最新條款。
