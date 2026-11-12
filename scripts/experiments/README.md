# Experiment scripts

One-off scripts from the development log (PLAN.md, docs/archive/PLAN-archive.md): each tried an idea offline on saved
analyses or on the validation clips, and its result is written down there. They are kept to show how a number was
made, **not maintained**: they use the pipeline's internals (`funscript_gen.pipeline`, `validate`, ...), which change,
so one may no longer run. Run them from the repository root, with the paths its docstring shows
(`uv run python scripts/experiments/NAME.py ...`). The scripts that are kept up to date (the validation tools, the
checks before a release) are in `scripts/`.
