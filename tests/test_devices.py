import numpy as np
import pytest
from typer.testing import CliRunner

from funscript_gen import devices
from funscript_gen.devices import DeviceError, check, use_gpu, wanted
from funscript_gen.pipeline import PipelineOptions


@pytest.fixture
def gpus(monkeypatch):
    """Which steps find a GPU: set found["flow"] = "name" to give the flow one (none by default)."""
    found = {}
    for step in devices.FINDERS:
        monkeypatch.setitem(devices.FINDERS, step, lambda step=step: found.get(step))
    monkeypatch.setattr(devices, "opencl_gpu", lambda: found.get("flow"))
    return found


def test_a_step_on_auto_follows_the_whole_run():
    assert wanted("flow", PipelineOptions()) == "auto"
    assert wanted("flow", PipelineOptions(compute="cpu")) == "cpu"
    assert wanted("flow", PipelineOptions(compute="cpu", flow_compute="gpu")) == "gpu"
    assert wanted("part", PipelineOptions(compute="gpu", part_compute="cpu")) == "cpu"


def test_auto_uses_a_gpu_only_when_there_is_one(gpus):
    assert not use_gpu("flow", PipelineOptions())
    gpus["flow"] = "Some GPU"
    assert use_gpu("flow", PipelineOptions()) and not use_gpu("flow", PipelineOptions(flow_compute="cpu"))
    assert not use_gpu("flow", PipelineOptions(compute="cpu"))


def test_gpu_without_one_stops_with_a_message(gpus):
    with pytest.raises(DeviceError) as e:
        use_gpu("part", PipelineOptions(part_compute="gpu"))
    assert "部位框偵測設定為 GPU" in e.value.local and "onnxruntime" in e.value.en
    with pytest.raises(DeviceError):
        check(PipelineOptions(compute="gpu"))


def test_only_the_steps_a_run_uses_are_checked(gpus):
    gpus["flow"] = "Some GPU"
    check(PipelineOptions(compute="gpu", part_sign=False))  # no part check, flow has a GPU, pose is not used
    check(PipelineOptions(pose_compute="gpu"))  # the skeletons are not used in the flow mode
    with pytest.raises(DeviceError, match="skeleton"):
        check(PipelineOptions(mode="pose", pose_compute="gpu", part_sign=False))


def test_part_detector_set_to_gpu_does_not_fall_back_to_the_cpu(monkeypatch):
    import onnxruntime as ort

    from test_parts import _FakeSession
    from funscript_gen.tracking import parts

    monkeypatch.setattr(ort, "get_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(ort, "InferenceSession", _FakeSession)  # DirectML fails to load
    assert parts.PartDetector("model.onnx").device == "CPUExecutionProvider"
    with pytest.raises(DeviceError):
        parts.PartDetector("model.onnx", require_gpu=True)


def test_flow_on_the_opencl_path_matches_the_cpu():
    """Without an OpenCL device the UMat path runs on the CPU (the same fields); on a GPU within a small error."""
    from funscript_gen.tracking.flow import FlowTracker

    rng = np.random.default_rng(0)
    base = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)
    frames = [np.roll(base, k, axis=0) for k in range(4)]
    cpu, gpu = FlowTracker(None, width=160), FlowTracker(None, width=160, gpu=True)
    for k, f in enumerate(frames):
        cpu.update(k * 33.0, f)
        gpu.update(k * 33.0, f)
    a, b = np.array(cpu.fields, np.float32), np.array(gpu.fields, np.float32)
    assert a.shape == b.shape and np.abs(a - b).mean() < 0.05


def test_generate_reports_where_the_flow_ran(tmp_path, monkeypatch, gpus):
    from funscript_gen import pipeline
    from funscript_gen.tracking import flow
    from test_parallel import _clip as clip

    clip(tmp_path / "c.mp4", seconds=2.0, cut_every_s=1.0)
    used = []
    real = flow.FlowTracker.__init__

    def spy(self, *args, gpu=False, **kw):
        used.append(gpu)
        real(self, *args, gpu=gpu, **kw)

    monkeypatch.setattr(flow.FlowTracker, "__init__", spy)
    opts = PipelineOptions(use_ai=False, part_sign=False, asym_audio=False, flow_workers=1)
    assert pipeline.generate(tmp_path / "c.mp4", opts).flow_device == "CPU" and not any(used)
    gpus["flow"] = "Test GPU"
    used.clear()
    assert pipeline.generate(tmp_path / "c.mp4", opts).flow_device == "OpenCL: Test GPU" and all(used)
    with pytest.raises(DeviceError):
        gpus.clear()
        pipeline.generate(tmp_path / "c.mp4", PipelineOptions(use_ai=False, compute="gpu"))


def test_cli_stops_before_generating_when_the_gpu_is_missing(tmp_path, gpus, monkeypatch):
    from funscript_gen import cli

    monkeypatch.setattr(cli, "generate", lambda *a, **k: pytest.fail("generated"))
    (tmp_path / "a.mp4").write_bytes(b"")
    r = CliRunner().invoke(cli.app, ["generate", str(tmp_path / "a.mp4"), "--flow-compute", "gpu"])
    assert r.exit_code == 1 and "no usable GPU" in r.output
    r = CliRunner().invoke(cli.app, ["generate", str(tmp_path / "a.mp4"), "--compute", "npu"])
    assert r.exit_code == 2  # not a choice


def test_web_ui_warns_and_stops_when_the_gpu_is_missing(tmp_path, gpus, monkeypatch):
    import gradio as gr

    from funscript_gen import webui as ui
    from funscript_gen.options import defaults

    monkeypatch.setattr(ui, "generate", lambda *a, **k: pytest.fail("generated"))
    (tmp_path / "a.mp4").write_bytes(b"")
    form = defaults() | {"compute": "gpu"}
    values = [form[n] for n in ui.FORM_NAMES]
    with pytest.raises(gr.Error, match="設定為 GPU"):
        ui.run(str(tmp_path / "a.mp4"), "", None, None, *values, progress=lambda *a, **k: None)


def test_compute_settings_are_segmented_controls_in_their_own_section():
    from funscript_gen.options import BY_NAME, build, defaults

    for name in ("compute", "flow_compute", "part_compute", "pose_compute"):
        o = BY_NAME[name]
        assert o.default == "auto" and o.control == "segmented" and o.group == "device"
        assert [v for _, v in o.choices] == ["auto", "gpu", "cpu"]
    opts = build(defaults() | {"compute": "cpu", "part_compute": "gpu"})
    assert (opts.compute, opts.flow_compute, opts.part_compute) == ("cpu", "auto", "gpu")
