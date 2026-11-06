# Contributing / 參與貢獻

Thanks for your interest. This project is licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE) (no commercial use).
感謝你的關注。本專案採用 [PolyForm Noncommercial 1.0.0](LICENSE) 授權（禁止商業使用）。

## Licence of contributions / 貢獻的授權

By submitting a pull request you agree that your contribution is released under the same license, and that the
author may also relicense it, for example to grant a commercial license to someone else.
提交 pull request 即表示你同意以同一授權釋出你的貢獻，並同意作者可以另行授權（例如對他人授與商業授權）。

## Before you open an issue or PR / 提出 issue 或 PR 之前

- **Never** upload videos, keyframes, hand-made `.funscript` files or API keys you do not own or may not share.
  Describe the problem with numbers (scores, logs) or a synthetic clip instead. See `tests/test_synthetic.py`.
- 請勿上傳你沒有權利分享的影片、關鍵幀、人工腳本或 API 金鑰；用數據（分數、紀錄）或合成影片描述問題。
- Do not submit content that involves minors or non-consensual imagery, or ask for help processing it.
  Such issues are closed and may be reported to GitHub.
  涉及未成年人或非自願影像的內容或求助一律不接受。

## Development / 開發

```bash
uv sync
uv run pytest
```

- Code, identifiers, comments and the first line of commit messages are in English. Text the user sees goes in
  `src/funscript_gen/lang/` (`zh-TW.toml`, `en.toml`; then run `uv run funscript-gen lang template`), not in code.
- New features need unit tests; a bug fix starts with a test that reproduces it.
- Changes to detection, signal or output logic should be checked with the validation runner (see
  [DEVELOPMENT.md](DEVELOPMENT.md)); the validation clips are private and not in this repository, so describe how you
  checked the change.
- 程式碼與註解用英文；使用者看得到的文字放語言包；新功能附測試；修改偵測／訊號／輸出邏輯請說明驗證方式（驗證素材是私人的，不在儲存庫中）。

## Versions / 版本

[Semantic Versioning](https://semver.org/); the version is written only in `src/funscript_gen/__init__.py`, and
releases are tagged `vX.Y.Z` by the maintainer. Pull requests do not change the version. Details in
[DEVELOPMENT.md](DEVELOPMENT.md#版本與發布).
版本號依 SemVer，只寫在 `__init__.py`，由維護者發布時加上 `vX.Y.Z` 標籤；PR 不需要改版本號。
