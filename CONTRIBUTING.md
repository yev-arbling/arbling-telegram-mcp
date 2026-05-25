# Contributing to arbling-telegram-mcp

## Development setup

```sh
git clone https://github.com/yev-arbling/arbling-telegram-mcp.git
cd arbling-telegram-mcp
pip install -e ".[dev]"
```

Run tests (no real Telegram account required — Telethon is mocked):

```sh
pytest
```

Authenticate locally before running the server:

```sh
# Set credentials from https://my.telegram.org
export TELEGRAM_API_ID=<your_id>
export TELEGRAM_API_HASH=<your_hash>

# One-time interactive login
arbling-telegram-mcp auth

# Discover your groups
arbling-telegram-mcp list-groups > ~/.arbling-telegram-mcp/curated-groups.yaml
# Edit the YAML, then run the server:
arbling-telegram-mcp
```

## Releasing a new version (Yevgeniy or Kairat)

Releases are fully automated via GitHub Actions + PyPI Trusted Publishing.
No tokens, no secrets — just a git tag.

### One-time PyPI setup (done for v0.1.0)

1. Go to https://pypi.org/manage/project/arbling-telegram-mcp/settings/publishing/
2. Click **Add a new publisher**
3. Fill in:
   - Owner: `yev-arbling`
   - Repository: `arbling-telegram-mcp`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`
4. Save. No token needed from this point on.

### Releasing a patch/minor/major

```sh
# 1. Bump the version in pyproject.toml
#    version = "0.1.1"   ← change this

# 2. Commit the bump
git add pyproject.toml
git commit -m "chore: bump version to 0.1.1"

# 3. Tag and push — Actions picks this up automatically
git tag v0.1.1
git push origin main --tags
```

GitHub Actions will:
1. Build `arbling_telegram_mcp-0.1.1.tar.gz` and the `.whl`
2. Publish both to PyPI via OIDC (no credentials in the workflow)
3. The new version appears at https://pypi.org/project/arbling-telegram-mcp/

### If the release run fails

```sh
git tag -d v0.1.1                        # delete local tag
git push origin :refs/tags/v0.1.1        # delete remote tag
# fix the issue, re-commit if needed
git tag v0.1.1
git push origin main --tags
```

## Adding a new tool

1. Add the async function in `src/arbling_telegram_mcp/client.py`.
2. Register it in `src/arbling_telegram_mcp/server.py` with `@mcp.tool()`.
3. Add tests in `tests/test_client.py` and `tests/test_server.py`.
4. Update the tool table in `README.md`.

## Hard constraints

- **Read-only**: no `send_message`, `join_group`, `leave_group`, `delete_message`, `mark_read`, or `react` tools. Write tools go in a separate PR and require explicit review.
- **No DMs**: never expose DMs or private chats. Filter at the Telethon client layer.
- **Curated-only**: `read_recent_messages`, `search_messages`, `get_message_thread` must reject non-curated group IDs at the client layer, not just the MCP tool layer.
- **No telemetry**: no outbound network calls beyond the Telegram API.
- **No secrets in code**: API credentials come from env vars only. Session files and curated-groups.yaml are gitignored.
- **Phone masking**: never log the user's phone number in plaintext.
