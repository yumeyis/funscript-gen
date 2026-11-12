"""The web UI's page: its components and how they are wired to the handlers in webui.py (build), the CSS and JS it
brings, and the helpers that make the path boxes and the settings form.

The handlers and state stay in webui.py (the tests and app.py reach them there); each function here takes the names it
needs from webui when it is called, not when this module is loaded, so webui and this module do not import each other
at load time and a name patched on webui is the one the page gets."""

from __future__ import annotations

import time

import gradio as gr

from funscript_gen import i18n, ollama_setup
from funscript_gen.i18n import L, Late, t
from funscript_gen.options import BY_NAME, GROUPS, PRESETS, UI_OPTIONS, group_title, preset_label, resolve

SEGMENTED_CSS = """
.segmented .wrap:has(> label) { display: inline-flex !important; flex-wrap: nowrap !important; gap: 0 !important;
  border: 1px solid var(--border-color-primary); border-radius: var(--radius-lg); overflow: hidden; }
.segmented label { margin: 0 !important; border: 0 !important; border-radius: 0 !important; box-shadow: none !important;
  padding: 6px 16px !important; justify-content: center; cursor: pointer; background: var(--background-fill-primary) !important; }
.segmented label + label { border-left: 1px solid var(--border-color-primary) !important; }
.segmented label input { display: none; }
.segmented label span { margin: 0 !important; }
.segmented label.selected { background: var(--color-accent) !important; color: white !important; }
"""


# Drop zones of the desktop app: a row with class fg-drop (id drop-<zone>). The window's drops reach Python
# (app.drop_handler: only it knows the files' paths), which calls fgDropped(paths); this script remembers which zone
# the drop was on and hands it, with the paths, to the hidden box fg-inbox, whose change event runs drop_arrived (an input event set from a script is not noticed).
UI_CSS = """
.fg-drop { border: 2px dashed transparent; border-radius: var(--radius-lg); padding: 2px; transition: border-color .1s; }
.fg-drop.fg-over { border-color: var(--color-accent); background: var(--background-fill-secondary); }
"""
UI_JS = """() => {
  if (window.fgDropped) return;
  let zone = '', n = 0;
  const files = e => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
  const find = e => (e.target.closest ? e.target.closest('.fg-drop') : null);
  const clear = () => document.querySelectorAll('.fg-over').forEach(el => el.classList.remove('fg-over'));
  // A file dropped anywhere that takes no drop would be opened by the window, replacing the app.
  window.addEventListener('dragover', e => {
    if (!files(e)) return;
    e.preventDefault(); clear();
    const el = find(e); if (el) el.classList.add('fg-over');
  }, true);
  window.addEventListener('dragleave', e => { if (!e.relatedTarget) clear(); }, true);
  window.addEventListener('drop', e => {
    if (!files(e)) return;
    e.preventDefault(); clear();
    const el = find(e); zone = el ? el.id.replace(/^drop-/, '') : '';
  }, true);
  window.fgDropped = paths => {
    const box = document.querySelector('#fg-inbox textarea');
    if (!zone || !box) return;
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    set.call(box, JSON.stringify({zone: zone, paths: paths, n: ++n}));
    box.dispatchEvent(new Event('input', {bubbles: true}));
    zone = '';
  };
}"""


def path_row(zone: str, label: str, buttons: dict[str, str], *, placeholder: str | None = None,
             info: str | None = None, lines: int = 1, visible: bool = True, elem_id: str | None = None):
    """A box of paths on this computer (the desktop app) that is also a drop zone `zone`, with a button beside it
    for each of `buttons` (dialog kind -> its text key). Returns the row, the box and the buttons in that order."""
    from funscript_gen.webui import (
        NATIVE_DIALOGS, ui,
    )
    with gr.Row(equal_height=True, elem_id=f"drop-{zone}", elem_classes=["fg-drop"], visible=visible) as row:
        box = ui(gr.Textbox, label=L(label), placeholder=L(placeholder) if placeholder else None,
                 info=L(info) if info else None, lines=lines, scale=4, elem_id=elem_id)
        with gr.Column(scale=1, min_width=140, visible=NATIVE_DIALOGS):
            picks = {kind: ui(gr.Button, value=L(key)) for kind, key in buttons.items()}
    return row, box, list(picks.values())


def _control(o):
    """The web UI control for option `o`: a choice with "" (the AI decides) is a dropdown, other choices radios
    (a segmented control when o.control says so, see SEGMENTED_CSS)."""
    from funscript_gen.webui import (
        ui,
    )
    kw = {"label": Late(lambda: o.label)} | ({"info": Late(lambda: o.info)} if o.info else {})
    if o.kind == "bool":
        return ui(gr.Checkbox, value=o.default, **kw)
    if o.kind == "choice":
        choices = Late(lambda: list(o.choices))
        if o.control == "segmented":
            return ui(gr.Radio, choices=choices, value=o.default, elem_classes=["segmented"], **kw)
        return ui(gr.Dropdown if "" in o.values else gr.Radio, choices=choices, value=o.default, **kw)
    if o.kind == "text":
        return ui(gr.Textbox, value=o.default, placeholder=Late(lambda: o.placeholder or None), **kw)
    lo, hi, step = o.slider
    return ui(gr.Slider, lo, hi, value=o.default, step=step, **kw)


# Option groups shown in the 設定 tab instead of the 產生 tab. They are still part of the 產生 form (run, batch,
# remembered with it), but a preset or 還原預設設定 leaves them alone, and a change there is remembered at once.
SETTINGS_TAB_GROUPS = ("device",)


def settings_form(after: dict | None = None, groups=None) -> tuple[dict, list]:
    """The settings laid out from UI_OPTIONS: an accordion per group (`groups`, default those of the 產生 tab),
    options sharing a row side by side, a row with show_if hidden while its switch is off. after[name]() adds
    components right after that option. Returns (option name -> component, [(switch name, row)])."""
    from funscript_gen.webui import (
        ui,
    )
    after = after or {}
    form, toggles = {}, []
    for group in groups or [g for g in GROUPS if g not in SETTINGS_TAB_GROUPS]:
        members = [o for o in UI_OPTIONS if o.group == group]
        with ui(gr.Accordion, label=Late(lambda group=group: group_title(group)), open=group != "advanced" and group not in SETTINGS_TAB_GROUPS):
            k = 0
            while k < len(members):
                o = members[k]
                if not o.row:
                    form[o.name] = _control(o)
                    k += 1
                    placed = [o]
                else:
                    placed = [o]
                    while k + len(placed) < len(members) and members[k + len(placed)].row == o.row:
                        placed.append(members[k + len(placed)])
                    with gr.Row(visible=bool(BY_NAME[o.show_if].default) if o.show_if else True) as row:
                        for m in placed:
                            form[m.name] = _control(m)
                    if o.show_if:
                        toggles.append((o.show_if, row))
                    k += len(placed)
                for m in placed:
                    if m.name in after:
                        after[m.name]()
    return form, toggles



LANGUAGE_LABEL = "語言 / Language"  # the one text that is not translated: it has to be findable in any language


def build() -> gr.Blocks:
    from funscript_gen.webui import (
        apply_language, ask_clear, ask_ollama_clear, backend_changed, backend_choices, batch_columns,
        bbox_choices, cancel_run, check_connection, choose, clear_ollama, clear_outputs, current_settings,
        delete_expired, drop_arrived, fetch_models, flip_at_time, flip_from_table, FORM_NAMES, load_last_form,
        LOCAL_FILES, ollama_mode_choices, ollama_status, open_batch_job, open_output_dir, output_list_html,
        output_status, output_store, pick_language, preview_cancel, preview_files, preview_files_whole,
        preview_flip, preview_flip_row, preview_rescene, preview_save, preview_video_uploaded,
        refresh_outputs, remember_settings_tab, restore_form, run, run_batch_ui, run_ollama, save_beside,
        save_edits, save_last_form, save_retention, save_settings, SCRIPT_SUFFIXES, toggle_reference,
        tool_cleared, tool_headers, tool_inspect, tool_run, tool_where_changed, translated_components, typed,
        ui, _ai_status, _last_file, _PLAYER_TIME_JS, _translated, _url_placeholder,
    )
    settings = current_settings()
    _translated.clear()
    with gr.Blocks(title="funscript-gen") as demo:
        gr.Markdown("# funscript-gen")
        with gr.Tabs() as tabs:
            with ui(gr.Tab, label=L("web.tab.gen"), id="gen"):
                with gr.Row():
                    with gr.Column(scale=2):
                        with gr.Row():
                            run_btn = ui(gr.Button, value=L("web.gen.run"), variant="primary", scale=4)
                            cancel_btn = ui(gr.Button, value=L("web.cancel"), variant="stop", scale=1)
                        run_msg = gr.Markdown()
                        if LOCAL_FILES:  # no uploads: the files are read where they are
                            video = gr.State(None)
                            _, video_local, (video_pick,) = path_row(
                                "gen-video", "web.gen.local_video", {"video": "web.pick"},
                                placeholder="web.gen.local_placeholder", info="web.gen.local_info", elem_id="local-video")
                            reference_ctl, reference, (reference_pick,) = path_row(
                                "gen-ref", "web.gen.reference", {"script": "web.pick"},
                                placeholder="web.gen.local_script_placeholder", info="web.drop.script_info",
                                visible=False)
                        else:
                            video = ui(gr.Video, label=L("web.gen.video"), sources=["upload"])
                            video_local = gr.State("")
                            reference = reference_ctl = ui(
                                gr.File, label=L("web.gen.reference"), file_types=[".funscript", ".json"],
                                type="filepath", visible=False)

                        with gr.Row():
                            preset = ui(gr.Dropdown, choices=Late(lambda: [(preset_label(k), k) for k in PRESETS]),
                                        value="default", label=L("web.gen.preset"),
                                                 info=L("web.gen.preset_info"), scale=4)
                            preset_btn = ui(gr.Button, value=L("web.gen.apply"), size="sm", scale=1)
                        extra = {}

                        def ai_status() -> None:
                            extra["status"] = gr.Markdown(_ai_status(settings))
                            extra["test_btn"] = ui(gr.Button, value=L("web.test_connection"), size="sm")

                        form, toggles = settings_form({"use_ai": ai_status})
                        status, test_btn = extra["status"], extra["test_btn"]
                        use_reference, scene_threshold = form["use_reference"], form["scene_threshold"]

                        with gr.Row():
                            form_msg = ui(gr.Markdown, value=L("web.gen.remember"))
                            reset_btn = ui(gr.Button, value=L("web.gen.reset"), size="sm", scale=0)

                    with gr.Column(scale=3):
                        ui(gr.Markdown, value=L("web.gen.preview_title"))
                        player = gr.HTML(elem_id="gen-player")
                        with gr.Row():
                            flip_btn = ui(gr.Button, value=L("web.flip"), size="sm", scale=0)
                            save_btn = ui(gr.Button, value=L("web.save_edits"), size="sm", scale=0)
                            flip_msg = ui(gr.Markdown, value=L("web.gen.flip_help"))
                        output_file = ui(gr.File, label=L("web.output_funscript"))
                        summary = gr.Markdown()
                        plot = ui(gr.Plot, label=L("web.gen.plot"))
                        scenes = ui(gr.Dataframe,
                            label=L("web.gen.scenes"),
                            interactive=False, wrap=True,
                        )
                        job = gr.State()
                        cur_t = gr.Number(visible=False)
                        cur_play = gr.Checkbox(visible=False)
                        cur_edits = gr.Textbox(visible=False)

            with ui(gr.Tab, label=L("web.tab.batch")):
                ui(gr.Markdown, value=L("web.batch.intro"))
                with gr.Row():
                    batch_btn = ui(gr.Button, value=L("web.batch.run"), variant="primary", scale=4)
                    batch_cancel = ui(gr.Button, value=L("web.cancel"), variant="stop", scale=1)
                batch_msg = gr.Markdown()
                if LOCAL_FILES:
                    batch_videos = gr.State(None)
                    _, batch_local, (batch_add_files, batch_add_folder) = path_row(
                        "batch", "web.batch.local", {"videos": "web.batch.pick_videos", "folder": "web.batch.pick_folder"},
                        info="web.batch.local_info", lines=4)
                else:
                    batch_videos = ui(gr.File, label=L("web.batch.videos"), file_count="multiple",
                                      file_types=["video"], type="filepath")
                    batch_local = gr.State("")
                batch_table = ui(gr.Dataframe, headers=Late(batch_columns), label=L("web.batch.result"), interactive=False, wrap=True)
                batch_files = ui(gr.File, label=L("web.output_funscript"), file_count="multiple")
                with gr.Row(equal_height=True):
                    batch_pick = ui(gr.Dropdown, [], label=L("web.batch.done_videos"), scale=4,
                                             info=L("web.batch.done_info"))
                    batch_open = ui(gr.Button, value=L("web.batch.open"), scale=1)
                batch_jobs = gr.State()

            with ui(gr.Tab, label=L("web.tab.preview")):
                ui(gr.Markdown, value=L("web.pv.intro"))
                if LOCAL_FILES:
                    pv_auto = ui(gr.Checkbox, label=L("web.pv.auto"), value=True, info=L("web.pv.auto_info"))
                    _, pv_video, (pv_video_pick,) = path_row(
                        "pv-video", "web.pv.video_local", {"video": "web.pick_video"},
                        placeholder="web.gen.local_placeholder", info="web.pv.video_info", elem_id="pv-video")
                    _, pv_script, (pv_script_pick,) = path_row(
                        "pv-script", "web.pv.script_local", {"script": "web.pick_script"},
                        placeholder="web.gen.local_script_placeholder", elem_id="pv-script")
                    _, pv_axes, (pv_axes_pick,) = path_row(
                        "pv-axes", "web.pv.axes_local", {"scripts": "web.tool.pick_scripts"},
                        info="web.pv.axes_info", lines=2, elem_id="pv-axes")
                    pv_ref_ctl, pv_ref, (pv_ref_pick,) = path_row(
                        "pv-ref", "web.pv.reference", {"script": "web.pick"},
                        placeholder="web.gen.local_script_placeholder", visible=False)
                else:
                    with gr.Row():
                        pv_video = ui(gr.File, label=L("web.pv.video"), file_count="multiple",
                                           file_types=["video", *SCRIPT_SUFFIXES], type="filepath", elem_id="pv-video")
                        pv_script = ui(gr.File, label=L("web.pv.script"), file_count="multiple",
                                       file_types=[".funscript", ".json"], type="filepath", elem_id="pv-script")
                    pv_axes = gr.State(None)
                    with gr.Row():
                        pv_ref = pv_ref_ctl = ui(gr.File, label=L("web.pv.reference"),
                                                 file_types=[".funscript", ".json"], type="filepath", visible=False)
                with gr.Row(equal_height=True):
                    pv_threshold = _control(BY_NAME["scene_threshold"])
                    pv_btn = ui(gr.Button, value=L("web.pv.load"), variant="primary", scale=0)
                    pv_whole = ui(gr.Button, value=L("web.pv.load_whole"), scale=0)
                    pv_cancel = ui(gr.Button, value=L("web.pv.cancel_load"), variant="stop", scale=0)
                    pv_rescene = ui(gr.Button, value=L("web.pv.rescene"), scale=0)
                pv_player = gr.HTML(elem_id="pv-player")
                with gr.Row():
                    pv_flip = ui(gr.Button, value=L("web.flip"), size="sm", scale=0)
                    pv_save = ui(gr.Button, value=L("web.save_edits"), size="sm", scale=0)
                    pv_msg = ui(gr.Markdown, value=L("web.pv.help"), elem_id="pv-msg")
                pv_out = ui(gr.File, label=L("web.pv.out"))
                pv_scenes = ui(gr.Dataframe,
                    label=L("web.pv.scenes"),
                    interactive=False, wrap=True,
                )
                pv_job = gr.State()
                pv_t = gr.Number(visible=False)
                pv_play = gr.Checkbox(visible=False)
                pv_edits = gr.Textbox(visible=False)

            with ui(gr.Tab, label=L("web.tab.tools"), id="tools"):
                ui(gr.Markdown, value=L("web.tool.intro"))
                if LOCAL_FILES:
                    tool_auto = ui(gr.Checkbox, label=L("web.tool.auto"), value=True, info=L("web.tool.auto_info"))
                    _, tool_in, (tool_in_pick,) = path_row(
                        "tool-in", "web.tool.files_local", {"scripts": "web.tool.pick_scripts"},
                        info="web.tool.files_info", lines=4, elem_id="tool-in")
                else:
                    tool_auto = gr.State(False)
                    tool_in = ui(gr.File, label=L("web.tool.files"), file_count="multiple",
                                 file_types=[".funscript", ".json"], type="filepath", elem_id="tool-in")
                tool_msg = gr.Markdown()
                tool_table = ui(gr.Dataframe, headers=Late(tool_headers), label=L("web.tool.table"),
                                interactive=False, wrap=True)
                tool_view = gr.HTML(elem_id="tool-view")
                if LOCAL_FILES:
                    tool_where = ui(gr.Radio, value="beside", label=L("web.tool.where"), info=L("web.tool.where_info"),
                                    choices=Late(lambda: [(t("web.tool.where_beside"), "beside"),
                                                          (t("web.tool.where_elsewhere"), "elsewhere")]))
                    tool_keep = ui(gr.Radio, value="backup", label=L("web.tool.keep"), info=L("web.tool.keep_info"),
                                   choices=Late(lambda: [(t("web.tool.keep_backup"), "backup"),
                                                         (t("web.tool.keep_overwrite"), "overwrite")]))
                    tool_out_row, tool_out, (tool_out_pick,) = path_row(
                        "tool-out", "web.tool.folder", {"folder": "web.tool.pick_folder"},
                        info="web.tool.folder_info", visible=False, elem_id="tool-out")
                else:
                    tool_where, tool_keep, tool_out = gr.State("beside"), gr.State("backup"), gr.State("")
                with gr.Row():
                    tool_merge = ui(gr.Button, value=L("web.tool.merge"), variant="primary", scale=0, visible=False)
                    tool_split = ui(gr.Button, value=L("web.tool.split"), variant="primary", scale=0, visible=False)
                tool_result = gr.Markdown()
                tool_files = ui(gr.File, label=L("web.tool.out"), file_count="multiple")
                tool_plan = gr.State()

            with ui(gr.Tab, label=L("web.tab.output")) as out_tab:
                ui(gr.Markdown, value=L("web.out.intro"))
                out_status = gr.Markdown(output_status)
                with gr.Row():
                    out_refresh = ui(gr.Button, value=L("web.out.refresh"))
                    out_open = ui(gr.Button, value=L("web.out.open"), visible=LOCAL_FILES)
                    out_clear = ui(gr.Button, value=L("web.out.clear"), variant="stop")
                with gr.Row(visible=False) as out_confirm_row:
                    ui(gr.Markdown, value=L("web.out.confirm_text"))
                    out_confirm = ui(gr.Button, value=L("web.out.confirm"), variant="stop")
                    out_cancel = ui(gr.Button, value=L("web.cancel"))
                out_msg = gr.Markdown()
                out_list = gr.HTML(output_list_html)

            with ui(gr.Tab, label=L("web.tab.settings")):
                set_lang = gr.Dropdown(i18n.choices(), value=i18n.current(), label=LANGUAGE_LABEL,
                                       info=t("web.set.lang_info"))
                with gr.Accordion("AI API", open=False):
                    ui(gr.Markdown,
                        value=L("web.set.intro")
                    )
                    ollama = settings.vllm_backend == "ollama"
                    set_backend = ui(gr.Radio, choices=Late(backend_choices), value=settings.vllm_backend, label=L("web.set.backend"),
                                           info=L("web.set.backend_info"))
                    set_url = ui(gr.Textbox, label=L("web.set.url"), value=settings.vllm_base_url,
                                         placeholder=Late(lambda: _url_placeholder("ollama" if ollama else "openai")))
                    set_key = ui(gr.Textbox,
                        label=L("web.set.key"), type="password", value="",
                        placeholder=Late(lambda: t("web.key_keep") if current_settings().vllm_api_key else t("web.key_unset")),
                        info=L("web.set.key_info"),
                    )
                    with gr.Row():
                        set_model = ui(gr.Dropdown,
                            [settings.vllm_model], value=settings.vllm_model, label=L("web.set.model"),
                            allow_custom_value=True, scale=4, info=L("web.set.model_info"),
                        )
                        set_fetch = ui(gr.Button, value=L("web.set.fetch"), scale=1)
                    set_bbox = ui(gr.Dropdown, choices=Late(bbox_choices), value=settings.vllm_bbox_format, label=L("web.set.bbox"),
                                           info=L("web.set.bbox_info"))
                    set_concurrency = ui(gr.Slider,
                        1, 32, value=settings.vllm_concurrency, step=1, label=L("web.set.concurrency"),
                        info=L("web.set.concurrency_info"),
                    )
                    set_num_ctx = ui(gr.Number,
                        value=settings.vllm_num_ctx, precision=0, minimum=2048, label=L("web.set.num_ctx"), visible=ollama,
                        info=L("web.set.num_ctx_info"),
                    )
                    with ui(gr.Group, visible=ollama) as ollama_box:
                        ui(gr.Markdown, value=L("web.ollama.intro"))
                        ollama_mode = ui(gr.Radio, choices=Late(ollama_mode_choices), label=L("web.ollama.mode"),
                                         value=next((m for m in ollama_setup.MODES if ollama_setup.available(m)),
                                                    ollama_setup.MODES[0]))
                        ollama_model = ui(gr.Dropdown, ollama_setup.MODELS, value=ollama_setup.DEFAULT_MODEL,
                                          allow_custom_value=True, label=L("web.ollama.model"),
                                          info=L("web.ollama.model_info"))
                        with gr.Row():
                            ollama_run = ui(gr.Button, value=L("web.ollama.run"), scale=2)
                            ollama_check = ui(gr.Button, value=L("web.ollama.check"))
                            ollama_clear = ui(gr.Button, value=L("web.ollama.clear"), variant="stop")
                        with gr.Row(visible=False) as ollama_confirm_row:
                            ui(gr.Markdown, value=L("web.ollama.clear_confirm"))
                            ollama_confirm = ui(gr.Button, value=L("web.ollama.clear_yes"), variant="stop")
                            ollama_cancel = ui(gr.Button, value=L("web.cancel"))
                    with gr.Row():
                        set_test = ui(gr.Button, value=L("web.test_connection"))
                        set_save = ui(gr.Button, value=L("web.set.save"), variant="primary")
                    set_status = gr.Markdown()

                settings_tab, settings_toggles = settings_form(
                    {"compute": lambda: ui(gr.Markdown, value=L("web.set.compute_note"))},
                    groups=SETTINGS_TAB_GROUPS)
                toggles += settings_toggles
                form = {name: (form | settings_tab)[name] for name in FORM_NAMES}  # run()'s parameter order

                with ui(gr.Accordion, label=L("web.set.files"), open=False):
                    ui(gr.Markdown, value=L("web.set.files_intro"))
                    set_out_status = gr.Markdown(output_status)
                    out_days = ui(gr.Number, value=lambda: output_store().retention_days, precision=0, minimum=0,
                                         label=L("web.set.days"), info=L("web.set.days_info"))
                    out_beside = ui(gr.Checkbox,
                        value=lambda: output_store().beside_video, label=L("web.set.beside"), visible=LOCAL_FILES,
                        info=L("web.set.beside_info"))
                    with gr.Row():
                        out_save = ui(gr.Button, value=L("web.set.save_retention"), variant="primary")
                        out_expire = ui(gr.Button, value=L("web.set.delete_expired"), variant="stop")
                    set_out_msg = gr.Markdown()

        if LOCAL_FILES:
            inbox = gr.Textbox(visible="hidden", elem_id="fg-inbox")  # where UI_JS puts the files dropped on the window
        test_btn.click(check_connection, outputs=status)
        lang_outputs = [*translated_components(), set_lang, status, out_status, set_out_status, out_list]
        set_lang.input(pick_language, inputs=set_lang, outputs=lang_outputs)
        demo.load(apply_language, outputs=lang_outputs)  # a page opened later follows the language chosen since
        use_reference.change(toggle_reference, inputs=use_reference, outputs=[reference_ctl, pv_ref_ctl])
        ai_form = [set_url, set_key, set_model, set_bbox, set_concurrency, set_backend, set_num_ctx]
        set_backend.change(backend_changed, inputs=[set_backend, set_url], outputs=[set_url, set_num_ctx, ollama_box])
        ollama_check.click(ollama_status, outputs=set_status)
        ollama_clear.click(lambda: ask_ollama_clear(True), outputs=ollama_confirm_row)
        ollama_cancel.click(lambda: ask_ollama_clear(False), outputs=ollama_confirm_row)
        ollama_confirm.click(clear_ollama, outputs=[set_status, ollama_confirm_row])
        ollama_run.click(run_ollama, inputs=[ollama_mode, ollama_model, set_concurrency],
                         outputs=[set_status, set_url, set_model, status, set_backend, set_num_ctx])
        set_fetch.click(fetch_models, inputs=ai_form, outputs=[set_model, set_status])
        set_test.click(check_connection, inputs=ai_form, outputs=set_status)
        set_save.click(save_settings, inputs=ai_form, outputs=[set_status, status, set_key])
        out_listing = [out_status, set_out_status, out_list]
        out_save.click(save_retention, inputs=out_days, outputs=[set_out_msg, *out_listing])
        out_expire.click(delete_expired, inputs=out_days, outputs=[set_out_msg, *out_listing])
        out_refresh.click(refresh_outputs, outputs=out_listing)
        out_tab.select(refresh_outputs, outputs=out_listing)
        out_clear.click(lambda: ask_clear(True), outputs=out_confirm_row)
        out_cancel.click(lambda: ask_clear(False), outputs=out_confirm_row)
        out_confirm.click(clear_outputs, outputs=[out_msg, *out_listing, out_confirm_row])
        # The keys are the names saved in _last_file; run() takes the values in this order after the two uploads.
        defaults = {k: c.value for k, c in form.items()}
        # Fires on restore, reset and presets too, so the sliders follow the remembered switches.
        for switch, row in toggles:
            form[switch].change(lambda on: gr.update(visible=on), inputs=form[switch], outputs=row)

        gen_form = {k: c for k, c in form.items() if k not in settings_tab}  # what presets and 還原預設設定 change

        def apply_preset(name):
            return [*restore_form(gen_form, resolve({}, name)),
                    t("web.gen.preset_applied", preset=preset_label(name), time=time.strftime('%H:%M:%S'))]

        preset_btn.click(apply_preset, inputs=preset, outputs=[*gen_form.values(), form_msg]).then(
            toggle_reference, inputs=use_reference, outputs=[reference_ctl, pv_ref_ctl])

        def remember(*values):
            save_last_form(dict(zip(form, values)))

        def reset_form():
            kept = {k: v for k, v in load_last_form().items() if k in settings_tab}
            if kept:
                save_last_form(kept)
            else:
                _last_file.unlink(missing_ok=True)
            return [*restore_form(gen_form, defaults), t("web.gen.reset_done", time=time.strftime('%H:%M:%S'))]

        for name, control in settings_tab.items():
            control.input(lambda v, name=name: remember_settings_tab({name: v}), inputs=control, queue=False)

        demo.load(lambda: restore_form(form, load_last_form()), outputs=list(form.values())).then(
            toggle_reference, inputs=use_reference, outputs=[reference_ctl, pv_ref_ctl]).then(
            lambda v: v, inputs=scene_threshold, outputs=pv_threshold)  # the 預覽 tab starts from the same threshold
        reset_btn.click(reset_form, outputs=[*gen_form.values(), form_msg]).then(
            toggle_reference, inputs=use_reference, outputs=[reference_ctl, pv_ref_ctl])
        run_btn.click(remember, inputs=list(form.values()), queue=False)
        run_btn.click(lambda: "", outputs=run_msg, queue=False)
        run_btn.click(
            run,
            inputs=[video, video_local, reference, job, *form.values()],
            outputs=[output_file, summary, plot, scenes, player, job, flip_msg],
        ).then(refresh_outputs, outputs=out_listing)
        cancel_btn.click(cancel_run, outputs=run_msg, queue=False)
        batch_btn.click(remember, inputs=list(form.values()), queue=False)
        batch_btn.click(lambda: "", outputs=batch_msg, queue=False)
        batch_btn.click(
            run_batch_ui,
            inputs=[batch_videos, batch_local, *form.values()],
            outputs=[batch_table, batch_files, batch_msg, batch_jobs, batch_pick],
        ).then(refresh_outputs, outputs=out_listing)
        batch_cancel.click(cancel_run, outputs=batch_msg, queue=False)
        batch_open.click(open_batch_job, inputs=[batch_jobs, batch_pick],
                         outputs=[output_file, summary, plot, scenes, player, job, flip_msg, video, video_local, tabs])
        if LOCAL_FILES:
            drops = [video_local, reference, batch_local, pv_video, pv_script, pv_ref, pv_axes, tool_in, tool_out, pv_msg]
            context = [batch_local, pv_auto, tool_auto]
            inbox.change(drop_arrived, inputs=[inbox, *context], outputs=drops)
            for zone, kind, button in (
                    ("gen-video", "video", video_pick), ("gen-ref", "script", reference_pick),
                    ("batch", "videos", batch_add_files), ("batch", "folder", batch_add_folder),
                    ("pv-video", "video", pv_video_pick), ("pv-script", "script", pv_script_pick),
                    ("pv-axes", "scripts", pv_axes_pick), ("pv-ref", "script", pv_ref_pick),
                    ("tool-in", "scripts", tool_in_pick), ("tool-out", "folder", tool_out_pick)):
                button.click(lambda text, auto, tool_auto, zone=zone, kind=kind:
                             choose(zone, kind, text, tool_auto if zone.startswith("tool-") else auto),
                             inputs=context, outputs=drops)
            for zone, box in (("pv-video", pv_video), ("pv-script", pv_script)):
                box.submit(lambda text, batch, auto, tool_auto, zone=zone: typed(zone, text, batch, auto),
                           inputs=[box, *context], outputs=drops)
        else:
            video.upload(lambda: "", outputs=video_local, queue=False)
        out_open.click(open_output_dir, outputs=out_msg)
        out_beside.input(save_beside, inputs=out_beside, outputs=set_out_msg, queue=False)
        flipped = [output_file, summary, plot, scenes, player, flip_msg]
        scenes.select(flip_from_table, inputs=[job, cur_t, cur_play, cur_edits], outputs=flipped,
                      js=_PLAYER_TIME_JS.format(id="gen-player"))
        flip_btn.click(flip_at_time, inputs=[job, cur_t, cur_play, cur_edits], outputs=flipped,
                       js=_PLAYER_TIME_JS.format(id="gen-player"))
        save_btn.click(save_edits, inputs=[job, cur_t, cur_play, cur_edits], outputs=flipped,
                       js=_PLAYER_TIME_JS.format(id="gen-player"))
        tool_inspected = [tool_plan, tool_msg, tool_table, tool_view, tool_merge, tool_split]
        tool_in.change(tool_inspect, inputs=tool_in, outputs=tool_inspected)
        if LOCAL_FILES:
            tool_where.change(tool_where_changed, inputs=tool_where, outputs=[tool_out_row, tool_keep], queue=False)
        for button in (tool_merge, tool_split):
            button.click(tool_run, inputs=[tool_plan, tool_where, tool_out, tool_keep],
                         outputs=[tool_result, tool_files]).success(tool_cleared, outputs=[tool_in, *tool_inspected])
        pv_outputs = [pv_player, pv_job, pv_out, pv_msg, pv_scenes]
        pv_js = _PLAYER_TIME_JS.format(id="pv-player")
        if not LOCAL_FILES:
            pv_video.upload(preview_video_uploaded, inputs=pv_video, outputs=[pv_video, pv_script, pv_msg])
        pv_btn.click(preview_files, inputs=[pv_video, pv_script, pv_ref, use_reference, pv_threshold, pv_axes],
                     outputs=pv_outputs)
        pv_whole.click(preview_files_whole, inputs=[pv_video, pv_script, pv_ref, use_reference, pv_threshold, pv_axes],
                       outputs=pv_outputs)
        pv_cancel.click(preview_cancel, outputs=pv_msg, queue=False)
        # The threshold goes between the job and the player's values: the JS passes the extra inputs through.
        pv_rescene_js = """(job, threshold, t, play, edits) => {{
  const r = ({js})(job, t, play, edits);
  return [r[0], threshold, r[1], r[2], r[3]];
}}""".format(js=pv_js)
        for trigger in (pv_rescene.click, pv_threshold.release):
            trigger(preview_rescene, inputs=[pv_job, pv_threshold, pv_t, pv_play, pv_edits], outputs=pv_outputs,
                    js=pv_rescene_js)
        pv_flip.click(preview_flip, inputs=[pv_job, pv_t, pv_play, pv_edits], outputs=pv_outputs, js=pv_js)
        pv_save.click(preview_save, inputs=[pv_job, pv_t, pv_play, pv_edits], outputs=pv_outputs, js=pv_js)
        pv_scenes.select(preview_flip_row, inputs=[pv_job, pv_t, pv_play, pv_edits], outputs=pv_outputs, js=pv_js)
    return demo


