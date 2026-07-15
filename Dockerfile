FROM python:3.12-slim

WORKDIR /app

# Install the package in a separate layer so dependency resolution is cached
# across rebuilds that only touch source files.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

# No secrets, curated-groups.yaml, or session files are baked into the image.
# All of that is injected at runtime via Railway environment variables:
# TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING,
# TELEGRAM_CURATED_GROUPS_B64, TELEGRAM_MCP_AUTH_TOKEN.

EXPOSE 8080

CMD ["arbling-telegram-mcp", "serve-http"]
