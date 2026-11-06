"""Where the analysis steps that can use a GPU run: auto | gpu | cpu for the whole run and for each step.

Three steps can: the optical flow (OpenCV's OpenCL), the part check (onnxruntime with a GPU provider) and the
skeletons (PyTorch). A step's "auto" follows the whole run's setting, whose "auto" uses a GPU when one is usable and
the CPU otherwise; "gpu" without a usable GPU stops the run before it starts (DeviceError). The rest stays on the CPU:
the AI runs on its own server, hardware video decoding gave the same frames but was slower than the CPU's (the frames
are decoded small, in many short pieces), and the render takes about a second.
"""

from __future__ import annotations

import functools
from typing import Literal

from funscript_gen.i18n import Late, t

Compute = Literal["auto", "gpu", "cpu"]
COMPUTE = ("auto", "gpu", "cpu")

# step -> (name, what it needs for a GPU), in English; the language packs have the web UI's text (device.step.*,
# device.needs.*)
STEPS = {
    "flow": ("the optical flow", "an OpenCL driver for the GPU"),
    "part": ("the part check", "a GPU build of onnxruntime (onnxruntime-gpu or onnxruntime-directml)"),
    "pose": ("the skeleton mode", "PyTorch with CUDA (uv sync --extra pose on a CUDA build)"),
}


class DeviceError(RuntimeError):
    """A step set to gpu (itself or through the whole run's setting) has no usable GPU. `en`: the message for the CLI;
    `local`: the web UI's, in the chosen language (the pack text `key` with `params`)."""

    def __init__(self, en: str, key: str, **params) -> None:
        super().__init__(en)
        self.en, self.key, self.params = en, key, params

    @property
    def local(self) -> str:
        return t(self.key, **self.params)


@functools.cache
def opencl_gpu() -> str | None:
    """The name of the OpenCL GPU OpenCV runs on; None without one (no driver, or only an OpenCL for the CPU)."""
    import cv2

    try:
        if not cv2.ocl.haveOpenCL():
            return None
        device = cv2.ocl.Device.getDefault()
        return device.name() if device.available() and device.type() & cv2.ocl.DEVICE_TYPE_GPU else None
    except cv2.error:
        return None


@functools.cache
def onnx_gpu() -> str | None:
    """The first GPU provider the installed onnxruntime offers (the part detector still checks that it loads)."""
    import onnxruntime as ort

    from funscript_gen.tracking.parts import GPU_PROVIDERS

    return next((p for p in GPU_PROVIDERS if p in ort.get_available_providers()), None)


@functools.cache
def torch_gpu() -> str | None:
    """The PyTorch device of a GPU ("0": the first CUDA one, "mps": Apple's); None without one or without PyTorch
    (the optional pose packages)."""
    try:
        import torch
    except ImportError:
        return None
    if torch.cuda.is_available():
        return "0"
    mps = getattr(torch.backends, "mps", None)
    return "mps" if mps is not None and mps.is_available() else None


FINDERS = {"flow": opencl_gpu, "part": onnx_gpu, "pose": torch_gpu}


def wanted(step: str, opts) -> str:
    """The setting `step` runs with: its own, or the whole run's when its own is auto."""
    own = getattr(opts, f"{step}_compute")
    return opts.compute if own == "auto" else own


def use_gpu(step: str, opts) -> bool:
    """Whether `step` runs on a GPU. Raises DeviceError when it is set to gpu and none is usable."""
    setting = wanted(step, opts)
    if setting == "cpu":
        return False
    if FINDERS[step]() is not None:
        return True
    if setting == "gpu":
        raise no_gpu(step)
    return False


def no_gpu(step: str) -> DeviceError:
    name, needs = STEPS[step]
    return DeviceError(f"{name} is set to GPU but no usable GPU was found (it needs {needs}); set it to auto or cpu",
                       "device.no_gpu", step=Late(lambda: t(f"device.step.{step}")),
                       needs=Late(lambda: t(f"device.needs.{step}")))


def steps(opts) -> list[str]:
    """The GPU-capable steps a run with `opts` uses."""
    used = ["pose"] if opts.mode == "pose" else ["flow"]
    return used + (["part"] if opts.part_sign else [])


def check(opts) -> None:
    """Raise DeviceError before a run when a step it uses is set to gpu and has no usable GPU."""
    for step in steps(opts):
        use_gpu(step, opts)
