FROM python:3.12-slim

# Install curl (for uv installer) and Node.js (for MCP servers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml .
COPY src/ src/

# Install Python dependencies (no dev deps in container)
RUN uv sync --no-dev

# Expose venv Python on PATH so "python" resolves without "uv run"
ENV PATH="/app/.venv/bin:$PATH"

# Pre-install MCP server npm packages for faster startup
RUN npm install -g \
    @modelcontextprotocol/server-github \
    @modelcontextprotocol/server-slack \
    @sooperset/mcp-atlassian \
    @playwright/mcp

# Store Playwright browsers under /app so the non-root user can access them
ENV PLAYWRIGHT_BROWSERS_PATH="/app/pw-browsers"

# Install Playwright + Chromium system deps (must run as root for apt)
RUN npx playwright install --with-deps chromium

# Create non-root user and transfer ownership of /app
RUN useradd -m appuser && chown -R appuser:appuser /app

USER appuser

# NOTE: .env is NOT copied into the image — supply secrets via --env-file at runtime
ENTRYPOINT ["python", "-m", "status_report.main"]
