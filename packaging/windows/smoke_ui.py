"""The web UI's own work for smoke-test.ps1: build the page (every Gradio component), make a script from a video as
the 產生 tab does (with the signal plot), and load it in the 預覽 tab. Catches what a pruned or broken package set
would break in the app (Gradio, pandas, matplotlib, scipy, the player) without opening a window.

usage: FUNSCRIPT_GEN_HOME=<data folder> runtime\\python.exe -I smoke_ui.py CLIP.mp4
"""

import sys

from funscript_gen import webui as ui

video = sys.argv[1]
ui.LOCAL_FILES = True
ui.create_app()  # builds the Blocks: all components and events
form = {n: ui.BY_NAME[n].default for n in ui.FORM_NAMES} | {"use_ai": False, "asym_audio": False, "flow_workers": 1}
out = ui.run(None, video, None, None, *[form[n] for n in ui.FORM_NAMES], progress=lambda *a, **k: None)
job = out[-2]
assert job.out_path.is_file(), "no script was written"
assert out[2] is not None, "no signal plot"
_, pjob, _, summary, table = ui.preview_files(video, str(job.out_path), "", False, 30.0)
assert pjob.video and len(table["value"]) >= 1, "the preview has no scenes"
print(f"web UI ok: {len(job.result.funscript.actions)} actions, {len(table['value'])} scene(s) in the preview")
