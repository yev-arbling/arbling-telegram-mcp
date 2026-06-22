# AGENTS.md — arbling-telegram-mcp (Claude Code + Codex)

> Thin contract. The **canonical** Arbling agent operating system (startup protocol,
> 9-domain scenario routing matrix, skill/subagent/MCP selection, launch/prod gates) lives in
> `…\arbling-audit-2026-06\Arbling-Scoring\AGENTS.md` and is mirrored in
> `C:\Users\yevma\Downloads\Arbling-Brain\CODEX.md`. Read one first; this file adds repo-specifics.

## Startup
1. Read `C:\Users\yevma\Downloads\Arbling-Brain\CODEX.md` and apply its scenario routing matrix.
2. Apply the CEO feedback rules (`…\Arbling-Brain\wiki\ceo\feedback\INDEX.md`).
3. **Anti-bloat law:** minimal relevant skills/subagents/MCP per task; never bundle-dump; announce selection, then act.
4. Converse in Russian; artifacts in English.

## This repo
- **Role:** the **read-only** Telegram MCP server (Telethon / MTProto) — reads curated Arbling groups for competitor news, market signals, and investor/mentor activity.
- **Stack:** Python, `pyproject.toml` (FastMCP-style server, Telethon). Tests via pytest.
- **Primary scenario:** "Market / deep research / competitor / customer intelligence" + "MCP building".
- **Skills · subagents · MCP:** `arbling-mcp-builder` + `api-and-interface-design`; `python-reviewer` + `security-reviewer`; the `arbling:scan-telegram` skill is the consumer.
- **Verify:** pytest green; session/auth handling robust; time-bounded reads (default last 24h).

## Do-not
- **Read-only invariant:** never add send/post/edit/delete-message tools — reading only.
- Never log or expose the Telethon session string, API id/hash, or message PII; redact.
- No unbounded scans — keep time/group limits.
