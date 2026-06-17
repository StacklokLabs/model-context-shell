#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

# Start MCP servers (requires Docker, runs on every Codespace start)
thv run mermaid 2>/dev/null || true
thv run fetch 2>/dev/null || true
thv run osv 2>/dev/null || true
thv run semgrep 2>/dev/null || true
