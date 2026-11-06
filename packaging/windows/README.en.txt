funscript-gen Windows portable build
====================================

[繁體中文: README.txt]

Use it right after extracting; there is no need to install Python or any other software. The whole folder can be put
anywhere that can be written to (for example the desktop, D:\ or a USB stick; not C:\Program Files). Deleting the
folder uninstalls it.

Requirements: Windows 10 or 11 (64-bit). The graphical interface uses the Microsoft Edge WebView2 that comes with the
system (built in on Windows 11; on Windows 10, when it is missing, the program opens the default browser instead).
The AI analysis needs a separate vLLM or Ollama server; on first use go to the Settings tab and enter the endpoint
and the model.


Graphical interface
-------------------
Double-click FunscriptGen.exe.

- In the Generate tab: press "Choose…" to pick a video (it is read as it is, with no upload), then press
  "Generate funscript".
- Scripts are kept in data\out\<time>\ by default. To save them beside the video (a .funscript with the video's
  name), tick "Also save the script beside the video" under "Output files" in the Settings tab.
  A script of the same name beside the video that this program did not make is never overwritten.
- Closing the window ends the program.


Command line
------------
Open a Command Prompt or PowerShell in this folder (or add the folder to PATH) and run funscript-gen.exe:

  funscript-gen.exe generate "D:\Videos\clip.mp4"            writes D:\Videos\clip.funscript
  funscript-gen.exe batch "D:\Videos" -o "D:\Scripts"         a whole folder
  funscript-gen.exe generate --help                          all arguments

The command line and the graphical interface share the same AI settings (data\.env).


Language
--------
The interface comes in Traditional Chinese and English. Choose it with the "語言 / Language" list at the top of the
Settings tab (it takes effect at once and is remembered), or on the command line with --lang en. When nothing is
chosen the system's language is used.

The language packs are the .toml files in the lang\ folder beside the exe. To add a language, copy
lang\_template.toml to lang\<code>.toml (for example lang\ja.toml), fill in code and name, and write each text; the
comment lines above each key show the Traditional Chinese and English texts. Check the file with

  funscript-gen.exe lang check lang\ja.toml

and reload the page; the new language is in the list.


The data folder
---------------
All files the program writes are in data\; nothing is written to the user's folders:
  .env                 The AI settings (with the API key)
  .webui-*.json        The settings the graphical interface remembers (including the language)
  out\                 The scripts the graphical interface made
  cache\               Caches of AI answers, the part detection model and its results, etc. (can be deleted;
                       they are made again)
  tmp\                 Temporary files (can be deleted)
  app.log              The graphical interface's log (look here when it cannot start)

To update: extract the new version, then copy the old version's data folder over to keep the settings and the caches.


Common questions
----------------
- On the first run Windows shows "Windows protected your PC": the program is not digitally signed.
  Press "More info" → "Run anyway".
- With a separate graphics card, optical flow and part detection use the GPU automatically (this can be set under
  "Compute device" in the Settings tab).


Usage notice, disclaimer and license
------------------------------------
- Please only process videos that you have a legal right to use, and only if you are of legal adult age in your
  jurisdiction; processing any unlawful content or content involving minors is strictly prohibited.
- When a generated .funscript is used to drive physical hardware devices, inspect the script in the preview first
  and set a safe stroke range and speed limit; this software is provided "AS IS", without warranty of any kind, and
  the authors are not liable for any hardware damage, data loss or personal injury.
- This project is licensed under the PolyForm Noncommercial License 1.0.0 (no commercial use; see LICENSE.txt); see THIRD_PARTY_NOTICES.md for third-party
  packages and models. This project was developed with Anthropic Claude (Claude Code).
