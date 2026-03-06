#!/usr/bin/env bash
set -euo pipefail

# Install Claude Code (Node.js provided via devcontainer feature)
npm install -g @anthropic-ai/claude-code

# Install thv (ToolHive) to ~/.local/bin
mkdir -p "$HOME/.local/bin"
curl -fsSL "https://github.com/stacklok/toolhive/releases/download/v0.11.0/toolhive_0.11.0_linux_amd64.tar.gz" \
  | tar -xz -C "$HOME/.local/bin" thv

export PATH="$HOME/.local/bin:$PATH"

# Ensure Claude Code config exists and onboarding is marked complete
if [ ! -f "$HOME/.claude.json" ]; then
  echo '{}' > "$HOME/.claude.json"
fi
node -e "
const fs = require('fs');
const path = '$HOME/.claude.json';
const config = JSON.parse(fs.readFileSync(path, 'utf8'));
config.hasCompletedOnboarding = true;
config.lastOnboardingVersion = '99.99.99';
fs.writeFileSync(path, JSON.stringify(config));
"

# Ensure VS Code Server MCP config exists so thv can register itself
mkdir -p "$HOME/.vscode-server/data/User"
if [ ! -f "$HOME/.vscode-server/data/User/mcp.json" ]; then
  echo '{}' > "$HOME/.vscode-server/data/User/mcp.json"
fi

# Register clients (Docker not needed for registration)
thv client register claude-code
thv client register vscode-server
