# Multi-stage build for model-context-shell
# Stage 1: Builder - install dependencies
FROM python:3.13-slim AS builder

# Create non-root user
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Install system dependencies needed for shell commands
RUN apt-get update && apt-get install -y \
    jq \
    grep \
    sed \
    gawk \
    coreutils \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory and change ownership
WORKDIR /app
RUN chown app:app /app

# Switch to non-root user
USER app

# Copy dependency files first for better caching
COPY --chown=app:app pyproject.toml uv.lock* ./
COPY --chown=app:app README.md ./

# Install dependencies using uv
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --no-dev --locked

# Copy application code
COPY --chown=app:app *.py ./

# Stage 2: Runtime - minimal image
FROM python:3.13-slim AS runner

# Create non-root user (same as builder)
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Install only runtime dependencies (shell commands)
RUN apt-get update && apt-get install -y \
    jq \
    grep \
    sed \
    gawk \
    coreutils \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app
RUN chown app:app /app

# Copy virtual environment and application from builder
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/*.py /app/

# Switch to non-root user
USER app

# Environment variables for container networking with ToolHive
# When running in Docker, ToolHive is accessible via host.docker.internal
# In Kubernetes, this would be the service name (e.g., "toolhive")
ENV TOOLHIVE_HOST=host.docker.internal
ENV TOOLHIVE_PORT=
ENV PATH="/app/.venv/bin:$PATH"

# Expose the MCP server port
EXPOSE 8000

# Health check
# TODO: This endpoint (/mcp/health) does not actually exist in FastMCP.
# Health checks will always fail until a custom health endpoint is implemented.
# To fix: Add @mcp.custom_route("/health", methods=["GET"]) in main.py
# and update this to check http://localhost:8000/health instead.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import httpx; httpx.get('http://localhost:8000/mcp/health', timeout=5.0)"] || exit 1

# Run the MCP server
# When TOOLHIVE_HOST is set, the code automatically binds to 0.0.0.0
CMD ["/app/.venv/bin/python", "main.py"]
