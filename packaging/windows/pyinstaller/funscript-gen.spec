# PyInstaller spec of the Windows build (build.ps1): one folder with two exes that share _internal\:
# FunscriptGen.exe (the app, no console) and funscript-gen.exe (the CLI). Both start from entry.py.
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas, binaries, hiddenimports = [], [], []
# Packages that load files or modules by name at run time: take everything of them. Gradio also needs its .py files
# (component_meta.py reads every component's source on import) and its frontend.
for package in ("gradio", "gradio_client", "safehttpx", "groovy", "uvicorn", "webview"):
    d, b, h = collect_all(package, include_py_files=package == "gradio")
    datas += d
    binaries += b
    hiddenimports += h
# Left out of Gradio's frontend: its server-side-rendering node app (SSR is off) and the pre-compressed .br copies of the
# assets (the files are served as they are).
datas = [d for d in datas if "templates/node" not in d[1].replace("\\", "/") and not d[0].endswith(".br")]
datas += collect_data_files("funscript_gen")  # the language packs and build-info.json inside the package
hiddenimports += collect_submodules("funscript_gen")

excludes = ["tkinter", "pytest", "IPython", "setuptools", "pip", "sympy"]

app = Analysis(["entry.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports, excludes=excludes)
cli = Analysis(["entry.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports, excludes=excludes)
pyz_app, pyz_cli = PYZ(app.pure), PYZ(cli.pure)
exe_app = EXE(pyz_app, app.scripts, [("X utf8", None, "OPTION")], exclude_binaries=True, name="FunscriptGen",
              console=False)
exe_cli = EXE(pyz_cli, cli.scripts, [("X utf8", None, "OPTION")], exclude_binaries=True, name="funscript-gen",
              console=True)
COLLECT(exe_app, app.binaries, app.datas, exe_cli, cli.binaries, cli.datas, name="FunscriptGen", strip=False,
        upx=False)
