# Model Context Shell

[![CI](https://github.com/StacklokLabs/mcp-shell/actions/workflows/ci.yml/badge.svg)](https://github.com/StacklokLabs/mcp-shell/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Unix-style pipelines for MCP tools — coordinate thousands of tool calls in a single request**

## Introduction

Model Context Shell is an [MCP](https://modelcontextprotocol.io/) server that lets AI agents compose tool calls using Unix shell patterns. Instead of the agent orchestrating each tool call individually (loading all intermediate data into context), agents can express complex workflows as pipelines that execute server-side.

The agent writes pipelines that conceptually work like this:

```
fetch users → jq (extract profile URLs) → for_each fetch → jq (filter active, sort)
```

This single pipeline fetches a list, extracts URLs, fetches each one, filters the results, and returns only the final output to the agent — no intermediate data in context.

### Why this matters

[MCP](https://modelcontextprotocol.io/) is great — standardized interfaces, structured data, extensible ecosystem. But for complex workflows, agents hit real limits:

| | Without | With |
|---|---|---|
| **Orchestration** | Agent coordinates every tool call, loading intermediate results into context | Single pipeline request, only final result returned |
| **Composition** | Tools combined through LLM reasoning | Native Unix-style piping between tools |
| **Data scale** | Limited by context window | Streaming/iterator model handles datasets larger than memory |
| **Reliability** | LLM-dependent control flow | Deterministic shell pipeline execution |
| **Permissions** | Complex tasks push toward full shell access | Sandboxed execution with allowed commands only |

### Real-world example

Example query: "List all Pokemon over 50 kg that have the chlorophyll ability"

Instead of 7+ separate tool calls loading all Pokemon data into context, the agent constructed a single pipeline that:
- Fetched the ability data
- Extracted Pokemon URLs
- Fetched each Pokemon's details (7 API calls)
- Filtered by weight and formatted the results

**Result**: 50%+ reduction in tokens and only the final answer loaded into context.

### How it works

The server exposes four tools to the agent via MCP:

| Tool | Purpose |
|---|---|
| `execute_pipeline` | Execute a pipeline of tool calls and shell commands |
| `list_all_tools` | Discover all tools available from MCP servers via [ToolHive](https://stacklok.com/download/) |
| `get_tool_details` | Get the full schema and description for a specific tool |
| `list_available_shell_commands` | Show the whitelist of allowed CLI commands |

The agent constructs pipelines as JSON arrays of stages. Data flows from one stage to the next, similar to Unix pipes. There are three stage types:

**Tool stages** call external MCP tools discovered through ToolHive:
```json
{"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "https://..."}}
```

**Command stages** transform data using whitelisted shell commands:
```json
{"type": "command", "command": "jq", "args": ["-c", ".results[] | {id, name}"]}
```

**Preview stages** show a summarized view of the data at any point in the pipeline, useful for the agent to understand the data structure before writing transformations:
```json
{"type": "preview", "chars": 3000}
```

Any tool stage can set `"for_each": true` to process items one-by-one. The preceding stage must output JSONL (one JSON object per line), and the tool is called once per line. Results are collected into an array. This enables patterns like "fetch a list of URLs, then fetch each one" in a single pipeline call, using a single reused connection for efficiency.

Here is a full example — a pipeline that fetches users, extracts their profile URLs, fetches each profile, and filters for active users:

```json
[
    {"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "https://api.example.com/users"}},
    {"type": "command", "command": "jq", "args": ["-c", ".[] | {url: .profile_url}"]},
    {"type": "tool", "name": "fetch", "server": "fetch", "for_each": true},
    {"type": "command", "command": "jq", "args": ["-c", "[.[] | select(.active)] | sort_by(.name)"]}
]
```

## Setup

### Prerequisites

- [ToolHive](https://stacklok.com/download/) (`thv`) — a runtime for managing MCP servers

### Quick start

Run the pre-built image from GitHub Container Registry:

```bash
# Linux (requires --network host)
thv run ghcr.io/stackloklabs/model-context-shell:latest --network host --foreground --transport streamable-http

# macOS / Windows (Docker Desktop bridge works automatically)
thv run ghcr.io/stackloklabs/model-context-shell:latest --foreground --transport streamable-http
```

Once running, Model Context Shell is available to any AI agent that ToolHive supports — no additional integration required. It works with any existing MCP servers running through ToolHive, and relies on ToolHive's authentication model for connected servers.

### Tips

**Connect only Model Context Shell to your agent** — For best results, don't connect individual MCP servers directly to the agent alongside Model Context Shell. When agents have direct access to tools, they may call them individually instead of composing efficient pipelines. The server can access all your MCP servers through ToolHive automatically.

**Some agents need encouragement** — Most agents will use the shell naturally for complex tasks, but some may need a hint in their system prompt (e.g., "Use Model Context Shell pipelines to combine multiple tool calls efficiently").

## Security

ToolHive runs Model Context Shell in an isolated container, so shell commands have no access to the host filesystem or network — only to explicitly configured MCP servers.

- **Allowed commands only**: A fixed whitelist of safe, read-only data transformation commands (`jq`, `grep`, `sed`, `awk`, `sort`, `uniq`, `cut`, `wc`, `head`, `tail`, `tr`, `date`, `bc`, `paste`, `shuf`, `join`, `sleep`)
- **No shell injection**: Commands are executed with `shell=False`, arguments passed separately
- **MCP tools only**: All external operations go through approved MCP servers

## Development

### Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for dependency management

### Setup

```bash
uv sync --group dev
```

### Running tests

```bash
uv run pytest
```

### Linting and type checking

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Contributing

Contributions, ideas, and feedback are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines, including our DCO sign-off requirement.

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
