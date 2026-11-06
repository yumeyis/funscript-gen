# Security Policy / 安全性政策

## Reporting a vulnerability / 回報漏洞

Please do **not** open a public issue for a security problem. Use GitHub's private vulnerability reporting
(repository **Security** tab → **Report a vulnerability**). Do not attach private videos or API keys.

請不要用公開的 issue 回報安全問題，改用 GitHub 的私人漏洞回報（儲存庫的 **Security** 分頁 → **Report a vulnerability**）。
請不要附上私人影片或 API 金鑰。

## Things to know / 使用時要知道的事

- The web UI is designed for **one user and has no login**. By default it listens on `127.0.0.1` only. If you open it
  to the LAN (`WEBUI_HOST` / `WEBUI_BIND` = `0.0.0.0`), anyone who can reach it can use it and change the AI endpoint
  and key. Open it only on a network you trust.
- The program collects no telemetry. Only sampled keyframes go to the AI endpoint you configure; use a server you run
  yourself. The API key is kept in `.env` (never committed).
- Web UI 設計給單人使用、沒有登入，預設只聽 `127.0.0.1`；開放區網後，能連到的人都能使用並修改 AI 端點與金鑰。
- 程式不收集遙測；只有鏡頭關鍵幀會送到你設定的 AI 端點，請用自己架設的伺服器。API 金鑰存在 `.env`（不提交）。

Only the latest release is supported. / 只維護最新的版本。
