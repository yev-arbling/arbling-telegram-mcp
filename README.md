# arbling-telegram-mcp

A read-only MCP (Model Context Protocol) server that gives Claude Code, Cowork, and any other MCP client access to a curated set of Telegram groups via your own Telegram account (MTProto). It reads only the groups you explicitly list in a hand-edited YAML config — not your full Telegram history, not DMs, not unlisted groups. All data stays local on your machine.

## Privacy

This server is read-only. It cannot send messages, join or leave groups, react, or delete anything. It never accesses your DMs or private conversations. It only reads the groups you explicitly add to `curated-groups.yaml`. Your Telegram session file stays on your machine — it is never transmitted or logged. Your phone number is masked in all output. There is no telemetry, analytics, or any outbound network traffic beyond the Telegram API itself.

## 5-step onboarding

```sh
# 1. Get Telegram API credentials (one-time, free)
#    Go to https://my.telegram.org → "API development tools"
#    Create an app, save api_id and api_hash to your password manager.

# 2. Install the package
pip install arbling-telegram-mcp
# or via uvx (no install needed):
# uvx arbling-telegram-mcp auth

# 3. Authenticate (one-time interactive — needs your phone for the SMS code)
TELEGRAM_API_ID=<your_id> TELEGRAM_API_HASH=<your_hash> arbling-telegram-mcp auth

# 4. Discover your groups and create the curated config
TELEGRAM_API_ID=<your_id> TELEGRAM_API_HASH=<your_hash> \
  arbling-telegram-mcp list-groups > ~/.arbling-telegram-mcp/curated-groups.yaml
# Edit the YAML: move groups you care about into tech_news / investor / tech_mentors
# Delete any groups you don't want the MCP to read.

# 5. Add to your MCP client config — see "Claude Code config" below
```

## Claude Code config (`~/.claude.json`)

```json
{
  "mcpServers": {
    "telegram": {
      "command": "arbling-telegram-mcp",
      "env": {
        "TELEGRAM_API_ID": "<your_id>",
        "TELEGRAM_API_HASH": "<your_hash>"
      }
    }
  }
}
```

## Cowork / desktop config

Add the same block to your Cowork MCP settings (the `mcpServers` section in the app's settings JSON):

```json
{
  "mcpServers": {
    "telegram": {
      "command": "arbling-telegram-mcp",
      "env": {
        "TELEGRAM_API_ID": "<your_id>",
        "TELEGRAM_API_HASH": "<your_hash>"
      }
    }
  }
}
```

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_API_ID` | Yes | — | Numeric API ID from https://my.telegram.org |
| `TELEGRAM_API_HASH` | Yes | — | API hash from https://my.telegram.org |
| `TELEGRAM_SESSION_PATH` | No | `~/.arbling-telegram-mcp/session` | Path to the Telethon `.session` file (without extension) |
| `TELEGRAM_CURATED_GROUPS_PATH` | No | `~/.arbling-telegram-mcp/curated-groups.yaml` | Path to your curated groups config |
| `TELEGRAM_SESSION_STRING` | Hosted only | — | Telethon StringSession (wins over the session file). See "Hosted deployment" |
| `TELEGRAM_CURATED_GROUPS_B64` | Hosted only | — | Base64-encoded curated-groups YAML (wins over the file path) |
| `TELEGRAM_MCP_AUTH_TOKEN` | Hosted only | — | Bearer token required by `serve-http`; the server refuses to start without it |
| `TELEGRAM_MCP_DISABLED` | No | — | Kill switch: any truthy value (`1`/`true`/`yes`/`on`) makes `serve-http` reject all tool calls with 503 |
| `PORT` | No | `8080` | Listen port for `serve-http` (set by Railway automatically) |

## Tools

| Tool | Description |
|---|---|
| `telegram_status` | Check connection + auth health. Call first in any session. |
| `list_my_groups` | List all groups/channels you're a member of (for discovery). |
| `list_curated_groups` | List groups from your curated-groups.yaml, optionally filtered by category. |
| `read_recent_messages` | Read recent messages from curated groups. Supports category filter, time window, single-group deep dive. |
| `search_messages` | Full-text search across curated groups with time window and category filter. |
| `get_message_thread` | Fetch a single message plus its reply thread. |
| `refresh_session` | Re-validate the session against Telegram (use when tools fail with auth errors). |

## curated-groups.yaml schema

```yaml
# Each category holds a list of groups identified by numeric Telegram chat_id.
# 'name' is descriptive only — for human readability and log output.
# Numeric chat_id is more reliable than @username (names can change).

tech_news:
  - id: -1001234567890
    name: "MCP Developers"
  - id: -1002345678901
    name: "Indie Hackers UAE"

investor:
  - id: -1009876543210
    name: "Pre-seed Underground"
  - id: -1009999999999
    name: "MENA Angels"

tech_mentors:
  - id: -1003333333333
    name: "AI Native Founders"
```

The three categories (`tech_news`, `investor`, `tech_mentors`) are the convention. Empty arrays are allowed. Extra top-level categories are forward-compatible.

To get the numeric IDs: run `arbling-telegram-mcp list-groups` — it outputs a YAML template with all your groups commented out, ready to edit.

## Hosted deployment (Railway)

The server can also run over HTTP for cloud callers (e.g. a daily-brief runner) via the `serve-http` subcommand — a stateless streamable-HTTP MCP endpoint at **`POST /mcp`**, protected by a mandatory bearer token. The repo ships a `Dockerfile` and `railway.json` (healthcheck on `/health`, restart `ON_FAILURE`), so deploying is: create a Railway service from this repo, set the variables below, done.

The read-only tool surface is identical to stdio mode — same 7 tools, no DMs, curated groups only.

### Required variables on Railway

| Variable | Purpose |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | Same API credentials as local mode |
| `TELEGRAM_SESSION_STRING` | Your Telegram session as a Telethon StringSession — set it with the export helper below, never by hand in logs/chat |
| `TELEGRAM_CURATED_GROUPS_B64` | Your `curated-groups.yaml`, base64-encoded (e.g. `base64 -w0 curated-groups.yaml`) |
| `TELEGRAM_MCP_AUTH_TOKEN` | Bearer token clients must send; generate with `openssl rand -hex 32`. **Fail closed**: the server refuses to start if unset |
| `TELEGRAM_MCP_DISABLED` | Optional kill switch — set to `1` to instantly reject all tool traffic (503) without deleting the service |

`PORT` is injected by Railway; `RAILWAY_GIT_COMMIT_SHA` is used by the health endpoint if present.

### Exporting your session

Run on the machine where you did `arbling-telegram-mcp auth` (requires the [Railway CLI](https://docs.railway.com/guides/cli), logged in and linked):

```sh
py -3.12 scripts/export_session_to_railway.py --service <service-name>
```

On macOS/Linux use `python3` instead of `py -3.12`.

The conversion is fully offline and the session string is never printed — only its length. Treat `TELEGRAM_SESSION_STRING` like a password: it grants read access as your account. If it ever leaks, log out that session from Telegram's active-sessions screen.

### Calling the hosted server

```sh
curl -X POST https://<your-app>.up.railway.app/mcp \
  -H "Authorization: Bearer $TELEGRAM_MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Requests without a valid token get `401`; when the kill switch is on, everything except `/health` gets `503`.

### Health endpoint

`GET /health` needs no auth and leaks no account or group data — booleans only:

```json
{"status": "ok", "sha": "<deploy commit>", "session_configured": true, "groups_configured": true}
```

When the kill switch is on, `status` is `"disabled"` but the HTTP status stays **200**: Railway uses this path for deploy health checks, and a 503 would fail the kill-switch redeploy and leave the previous, still-enabled process running. Tool traffic is still rejected with 503 by the auth middleware. If you need a hard stop instead of the soft kill switch, take the service down entirely with `railway down`.

## Troubleshooting

**Session not initialized**
Run `arbling-telegram-mcp auth` first. The session file must exist before starting the MCP server.

**Session expired**
If you see `status: expired` from `refresh_session`, the session was invalidated (you may have logged out on another device, or Telegram revoked it). Run `arbling-telegram-mcp auth` again.

**Group not found / 403 error**
The group ID in your YAML may be wrong or you may have left the group. Run `arbling-telegram-mcp list-groups` to rediscover and update the YAML.

**`read_recent_messages` rejects a group_id I passed**
The group must be in `curated-groups.yaml`. Add it to the YAML first.

**Telegram API rate limits (FloodWait)**
Telethon handles flood waits automatically. For large group lists with `since='7d'` + `limit=500`, expect the call to take 10–30 seconds. The server logs a warning when a wait exceeds 5 seconds.

**YAML malformed**
`list_curated_groups` returns a dict with an `error` key if the YAML can't be parsed. Fix the YAML manually or regenerate with `list-groups`.

**`TELEGRAM_API_ID must be a number`**
The API ID from https://my.telegram.org is always numeric (e.g., `12345678`), not a string.

## Development

```sh
git clone https://github.com/yev-arbling/arbling-telegram-mcp.git
cd arbling-telegram-mcp
pip install -e ".[dev]"
pytest
```

Tests mock Telethon — no real Telegram account needed for CI.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the release-by-tag workflow.

## Design decisions

1. **Numeric chat_id in YAML**: more reliable than `@username` — channel usernames can change. `list-groups` outputs numeric IDs. `@username` lookup is not supported in v0.1 to keep the dependency surface small.
2. **Rate limit behavior**: Telethon's built-in flood-wait handling is respected. Waits >5s are logged. Practical max query rate is ~30 messages/sec across all groups.
3. **Media handling**: non-text messages (photos, videos, voice notes) are skipped in `read_recent_messages` and counted in `media_skipped`. The agent reads text; binary content is out of scope for v0.1.
4. **Sender attribution**: signed channel posts include the signed-by name in the `sender` field; otherwise falls back to `@username` or display name.

## License

Apache 2.0 — see [LICENSE](LICENSE).
