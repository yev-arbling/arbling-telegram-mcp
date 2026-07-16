# Pinned by manifest-list digest (not just the `3.12-slim` tag) so the base
# image is immutable and reproducible across rebuilds — the tag is kept
# alongside the digest for human readability only; Docker resolves by digest.
# This is the multi-arch manifest-list digest (`docker.io/library/python`,
# tag `3.12-slim`); Docker selects the linux/amd64 child manifest from it at
# build time, matching Railway's build platform.
# Re-pin: crane digest python:3.12-slim   (or the Docker Hub registry API)
FROM python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28

WORKDIR /app

# Install the exact pinned dependency closure first, in its own layer, so
# dependency resolution is cached across rebuilds that only touch source
# files. requirements-lock.txt pins every transitive version (see that file's
# header for regeneration instructions); pyproject.toml stays the source of
# truth for version ranges.
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY pyproject.toml README.md ./
COPY src ./src

# --no-deps: the lock file above already installed the full dependency
# closure. Without --no-deps, pip would re-resolve pyproject.toml's open
# ranges here and could silently pull a different (newer) version than what
# was just pinned and tested.
RUN pip install --no-cache-dir --no-deps .

# Run as a non-root, unprivileged system account. Defense in depth: even
# though Railway's runtime is itself sandboxed, the process should never
# hold root inside its own container. UID pinned explicitly (999) so it is
# stable across base-image changes, not incidental to Debian's
# first-free-SYS_UID allocation.
RUN useradd --system --uid 999 --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

# No secrets, curated-groups.yaml, or session files are baked into the image.
# All of that is injected at runtime via Railway environment variables:
# TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING,
# TELEGRAM_CURATED_GROUPS_B64, TELEGRAM_MCP_AUTH_TOKEN.

EXPOSE 8080

CMD ["arbling-telegram-mcp", "serve-http"]
