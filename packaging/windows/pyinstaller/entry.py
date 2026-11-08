"""Entry of the PyInstaller build's two exes (funscript-gen.spec). Both do what packaging/windows/launcher.cs does for
the runtime\\python.exe build: find the folder they are in, keep every file the program writes in its data\\
(FUNSCRIPT_GEN_HOME, TEMP), point FUNSCRIPT_GEN_LANG_DIR at lang\\ beside the exe, and only then import the program.

FunscriptGen.exe (windowed) runs funscript_gen.app.main, funscript-gen.exe (console) funscript_gen.cli.app.
"""

import os
import sys

if sys.platform == "win32" and sys.stdout is None:  # windowed: no console, nowhere to print
    GUI = True
else:
    GUI = False


def fail(message: str) -> None:
    if GUI:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "funscript-gen", 0x10)  # MB_ICONERROR
    else:
        print(message, file=sys.stderr)
    raise SystemExit(1)


root = os.path.dirname(os.path.abspath(sys.executable))
data = os.path.join(root, "data")
temp = os.path.join(data, "tmp")
try:
    os.makedirs(temp, exist_ok=True)
except OSError as e:
    fail(f"Cannot create the folder {temp}: {e}\nPut the program where it can write (for example the desktop or "
         f"D:\\), not in Program Files.\n\n無法建立資料夾 {temp}：{e}\n請把程式放在可以寫入的位置（例如桌面或 D:\\），"
         f"不要放在 Program Files。")
os.environ["FUNSCRIPT_GEN_HOME"] = data
os.environ["FUNSCRIPT_GEN_LANG_DIR"] = os.path.join(root, "lang")
os.environ["TEMP"] = os.environ["TMP"] = temp

if GUI:
    from funscript_gen.app import main

    main()
else:
    from funscript_gen.cli import app

    app()
