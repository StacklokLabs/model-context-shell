# MCP Shell

**Unix-style pipelines for MCP tools — coordinate thousands of tool calls in a single request**

## Overview

MCP Shell is an MCP server that lets AI agents compose tool calls using Unix shell patterns. Instead of the agent orchestrating each tool call individually (loading all intermediate data into context), agents can express complex workflows as pipelines that execute server-side.

```bash
# What agents can express:
fetch https://api.example.com/users \
  | jq -c '.[] | .profile_url' \
  | for_each fetch \
  | jq '[.[] | select(.active)] | sort_by(.name)'
```

This single pipeline fetches a list, extracts URLs, fetches each one, filters the results, and returns only the final output to the agent — no intermediate data in context.

## Why This Matters

MCP is great — standardized interfaces, structured data, extensible ecosystem. But for complex workflows, agents hit real limits:

| | Without MCP Shell | With MCP Shell |
|---|---|---|
| **Orchestration** | Agent coordinates every tool call, loading intermediate results into context | Single pipeline request, only final result returned |
| **Composition** | Tools combined through LLM reasoning | Native Unix-style piping between tools |
| **Data scale** | Limited by context window | Streaming/iterator model handles datasets larger than memory |
| **Reliability** | LLM-dependent control flow | Deterministic shell pipeline execution |
| **Permissions** | Complex tasks push toward full shell access | Sandboxed execution with allowed commands only |

## Real-World Example

Example query: "List all Pokemon over 50 kg that have the chlorophyll ability"

Instead of 7+ separate tool calls loading all Pokemon data into context, the agent constructed a single pipeline that:
- Fetched the ability data
- Extracted Pokemon URLs
- Fetched each Pokemon's details (7 API calls)
- Filtered by weight and formatted the results

**Result**: 50%+ reduction in tokens and only the final answer loaded into context.

## Installation

### Prerequisites

- [ToolHive](https://toolhive.ai) (`thv`) for running and managing MCP servers

### Quick Start

Run the pre-built image from GitHub Container Registry:

```bash
# Linux (requires --network host)
thv run ghcr.io/stackloklabs/model-context-shell:latest --network host --foreground --transport streamable-http

# macOS / Windows (Docker Desktop bridge works automatically)
thv run ghcr.io/stackloklabs/model-context-shell:latest --foreground --transport streamable-http
```

Once running, MCP Shell is available to any AI agent that ToolHive supports — no additional integration required.

## Security

MCP Shell runs in a containerized environment through ToolHive, so commands have no direct access to the user's filesystem — only through explicitly configured MCP servers.

- **Containerized**: Runs isolated from the host system
- **Allowed Commands**: Only safe, read-only data transformation commands are permitted
- **No Shell Injection**: Commands are executed with `shell=False`, args passed separately
- **MCP Tools Only**: All external operations go through approved MCP servers

## Usage Tips

**Connect only MCP Shell to your agent** — For best results, don't connect individual MCP servers directly to the agent alongside MCP Shell. When agents have direct access to tools, they may call them individually instead of composing efficient pipelines. MCP Shell can access all your MCP servers through ToolHive automatically.

**Some agents need encouragement** — Most agents will use the shell naturally for complex tasks, but some may need a hint in their system prompt (e.g., "Use MCP Shell pipelines to combine multiple tool calls efficiently").

## FAQ

**Q: Does this work with my existing MCP servers?**

A: Yes! MCP Shell coordinates any standard MCP servers running through ToolHive.

**Q: What about authentication?**

A: Currently relies on ToolHive's authentication model for connected MCP servers.

## Contributing

This is an experimental project. Contributions, ideas, and feedback are welcome!

## License

[To be determined]

## Credits

Developed by Dániel Kántor at ToolHive.

---

**Note**: This is an experimental project exploring new patterns for AI agent coordination. The approach has proven effective in testing but needs broader testing and community feedback.
