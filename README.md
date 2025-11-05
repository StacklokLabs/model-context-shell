# MCP Shell

**A shell interface for coordinating MCP tool calls using Unix-style pipelines**

## Overview

MCP Shell is an experimental MCP server that enables AI agents to coordinate multiple tool calls using familiar Unix shell patterns. Instead of making sequential tool calls that load all data into model context, agents can construct complex data processing workflows as single pipeline operations.

## The Problem

The Model Context Protocol (MCP) provides a standardized interface for tool calls, but has limitations when it comes to complex workflows:

- **Sequential coordination**: Multiple tool calls must be coordinated by the agent, reading full responses into context each time
- **Context limitations**: All data must fit into the model's context window
- **Limited composition**: No standardized way to combine tools beyond agent-level orchestration
- **Token waste**: Agents must process all intermediate data, even when only the final result matters
- **Default to shell access**: Coding agents often resort to full system shell access for complex tasks, creating security concerns and approval fatigue

## The Solution

MCP Shell allows agents to coordinate tool calls using Unix shell patterns:

```bash
# Conceptually, agents can now do this:
fetch https://api.example.com/pokemon/ability/34 | \
  jq -c '.pokemon[] | .pokemon.url' | \
  for_each fetch | \
  jq '[.[] | select(.weight > 500)] | sort_by(.name)'
```

### Key Benefits

1. **Reduced token usage**: Only final results are loaded into model context, not intermediate data
2. **Scalability**: Can handle thousands of tool calls without hitting context limits
3. **Streaming**: Data flows between stages using iterators, handling datasets larger than memory
4. **Security**: Sandboxed execution with whitelisted commands, no full system access needed
5. **Standardized**: Works across different AI agents without custom integration
6. **Agent-ready**: Works out-of-the-box with existing models and agents (no retraining needed)

## Real-World Example

From the demo: "List all Pokemon over 50 kg that have the chlorophyll ability"

Instead of 7+ separate tool calls loading all Pokemon data into context, the agent constructed a single pipeline:

```python
[
  {"type": "tool", "name": "fetch", "server": "fetch",
   "args": {"url": "https://pokeapi.co/api/v2/ability/34/"}},
  {"type": "command", "command": "jq",
   "args": ["-c", ".pokemon[].pokemon.url"]},
  {"type": "tool", "name": "fetch", "server": "fetch", "for_each": true},
  {"type": "command", "command": "jq",
   "args": ["-s", "[.[] | select(.weight > 500)] | sort_by(.name)"]}
]
```

This single call:
- Fetched the ability data
- Extracted Pokemon URLs
- Fetched each Pokemon's details (7 API calls)
- Filtered by weight and formatted the results

**Result**: Massive reduction in tokens (50%+ in testing) and only the final answer loaded into context.

## Installation

### Prerequisites

- Python 3.13+
- bubblewrap (`bwrap`) installed and available in PATH (required)
- [ToolHive](https://toolhive.ai) (for managing MCP servers)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

Notes:
- On Debian/Ubuntu: `sudo apt-get install bubblewrap`
- On Fedora: `sudo dnf install bubblewrap`
- On macOS, bubblewrap is Linux-only; run this server inside Docker/Colima or a Linux VM with bubblewrap installed

### Install via ToolHive

```bash
# Coming soon - will be installable directly through ToolHive
thv install mcp-shell
```

### Manual Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/mcp-shell.git
cd mcp-shell

# Install dependencies
uv sync
# or with pip
pip install -e .

# Start the server
uv run python main.py
```

## Usage

### Starting the Server

```bash
# Default: HTTP transport on port 8000
python main.py

# Stdio transport (for direct MCP client integration)
python main.py --transport stdio

# Custom port
python main.py --port 8080

# Environment variables (used if no CLI flags provided)
# MCP_PORT: Override listening port (default 8000)
# MCP_HOST: Override bind host (default 127.0.0.1; 0.0.0.0 in containers)
# Example:
MCP_PORT=8081 MCP_HOST=0.0.0.0 python main.py
```

### Run with ToolHive

You can run the server as a ToolHive workload and proxy it via HTTP:

```bash
# Run from the registry with HTTP proxying (recommended simple setup)
thv run model-context-shell --network host --foreground --transport streamable-http
```

- `--network host`: Exposes the server on the host network so ToolHive can reach `http://127.0.0.1:<MCP_PORT>` directly (no extra port mapping).
- `--foreground`: Keeps the process attached in your terminal.
- `--transport streamable-http`: Matches the server’s default transport and exposes `/mcp`.

Notes:
- The server respects `MCP_PORT`/`MCP_HOST`. To override the port when running with ToolHive, pass env vars: `thv run model-context-shell -e MCP_PORT=8081 --network host --foreground --transport streamable-http`.
- On Linux with `--network host`, set the ToolHive host explicitly: `-e TOOLHIVE_HOST=127.0.0.1`. On Docker Desktop (macOS/Windows), use `-e TOOLHIVE_HOST=host.docker.internal`.
- Alternatively, you can use stdio transport: `thv run model-context-shell --foreground --transport stdio` (ToolHive will proxy it over SSE/HTTP).

### Available Tools

#### `execute_pipeline`

Execute a pipeline of tool calls and shell commands. This is the core functionality.

**Parameters:**
- `pipeline` (list): Array of pipeline stages
- `initial_input` (string, optional): Initial data to feed into the pipeline

**Pipeline Stage Types:**

1. **Tool Stage**: Call an MCP tool
```python
{
  "type": "tool",
  "name": "fetch",           # Tool name
  "server": "fetch",         # MCP server name
  "args": {"url": "..."},    # Tool arguments
  "for_each": false,         # Optional: run once per input line
  "save_to": "buffer_name"   # Optional: save output to named buffer
}
```

2. **Command Stage**: Run a whitelisted shell command
```python
{
  "type": "command",
  "command": "jq",           # Command name (must be whitelisted)
  "args": ["-c", ".foo"],    # Command arguments as array
  "for_each": false,         # Optional: run once per input line
  "save_to": "buffer_name"   # Optional: save output to named buffer
}
```

3. **Read Buffers**: Retrieve saved buffer contents
```python
{
  "type": "read_buffers",
  "buffers": ["buffer1", "buffer2"]  # Returns JSON object with buffer contents
}
```

#### `list_all_tools`

Lists all available MCP tools from connected ToolHive servers.

#### `list_available_shell_commands`

Returns the list of whitelisted shell commands available for use in pipelines.

### Whitelisted Commands

For security, only safe data transformation commands are allowed:

- **JSON/Data**: `jq`
- **Text Processing**: `grep`, `sed`, `awk`, `cut`, `tr`
- **Organization**: `sort`, `uniq`, `head`, `tail`, `wc`
- **Utilities**: `echo`, `printf`, `date`, `bc`, `paste`, `shuf`, `join`

## Examples

### Basic Pipeline: Fetch and Transform

```python
{
  "pipeline": [
    {
      "type": "tool",
      "name": "fetch",
      "server": "fetch",
      "args": {"url": "https://api.example.com/data"}
    },
    {
      "type": "command",
      "command": "jq",
      "args": [".items[] | {id, name}"]
    },
    {
      "type": "command",
      "command": "grep",
      "args": ["-i", "search_term"]
    }
  ]
}
```

### Advanced: for_each Pattern

The `for_each` flag processes each line independently:

```python
{
  "pipeline": [
    # Get list of URLs
    {
      "type": "tool",
      "name": "fetch",
      "server": "fetch",
      "args": {"url": "https://api.example.com/items"}
    },
    # Transform to JSONL format (one JSON object per line)
    {
      "type": "command",
      "command": "jq",
      "args": ["-c", ".items[] | {url: .detail_url}"]
    },
    # Fetch each URL individually
    {
      "type": "tool",
      "name": "fetch",
      "server": "fetch",
      "for_each": true
    },
    # Aggregate and sort results
    {
      "type": "command",
      "command": "jq",
      "args": ["-s", "sort_by(.created_at)"]
    }
  ]
}
```

### Using Buffers

Save intermediate results for later retrieval:

```python
{
  "pipeline": [
    {
      "type": "tool",
      "name": "fetch",
      "server": "fetch",
      "args": {"url": "..."},
      "save_to": "raw_data"
    },
    {
      "type": "command",
      "command": "jq",
      "args": [".items[]"],
      "save_to": "items"
    },
    {
      "type": "command",
      "command": "jq",
      "args": ["length"]
    },
    # Later: retrieve both saved buffers
    {
      "type": "read_buffers",
      "buffers": ["raw_data", "items"]
    }
  ]
}
```

## Architecture

MCP Shell acts as a coordinator between AI agents and MCP tools:

```
AI Agent
   ↓ (single pipeline request)
MCP Shell
   ↓ (coordinates multiple tools)
ToolHive → MCP Server 1 (e.g., fetch)
        → MCP Server 2 (e.g., database)
        → MCP Server 3 (e.g., filesystem)
```

Data flows through the pipeline using Python iterators, enabling:
- Streaming processing (no need to load all data at once)
- Lazy evaluation (stages only process when needed)
- Memory efficiency (can handle datasets larger than RAM)

## Security

MCP Shell is designed with security in mind:

1. **Command Whitelisting**: Only safe, read-only data transformation commands are allowed
2. **No Shell Injection**: Commands are executed with `shell=False`, args passed separately
3. **Sandboxed Execution**: No access to arbitrary file system or network operations
4. **MCP Tools Only**: All external operations go through approved MCP servers
5. **No System Access**: Doesn't require or provide full system shell access

## Design Philosophy

### Build Complete Pipelines

**✅ DO**: Construct the entire workflow as a single pipeline
```python
execute_pipeline([
  {"type": "tool", "name": "fetch", ...},
  {"type": "command", "command": "jq", "args": [...]},
  {"type": "tool", "name": "process", "for_each": true}
])
```

**❌ DON'T**: Make multiple pipeline calls with manual data passing
```python
# Anti-pattern
result1 = execute_pipeline([{"type": "tool", ...}])
# Manually parse result1 in agent context
result2 = execute_pipeline([{"type": "tool", "args": {"data": result1}}])
```

### Why This Matters

- **Token efficiency**: Intermediate data doesn't inflate context
- **Reliability**: Shell commands provide deterministic data transformation
- **Scalability**: Can coordinate hundreds of tool calls in one pipeline
- **Agent simplicity**: Agent just describes the workflow, doesn't manage data flow

## Testing

The project demonstrated 50%+ token savings in real-world tests, with the agent successfully using the shell without any special training or configuration.

**Test results**:
- ✅ Agents can use the shell out-of-the-box (no model retraining needed)
- ✅ Works through MCP protocol (no custom agent integration required)
- ✅ Agents naturally use it for appropriate complex tasks
- ✅ Reliable: Same pipeline generated consistently (20+ test runs)

## Roadmap

- [ ] Open source release with documentation
- [ ] Integration with ToolHive ecosystem
- [ ] Video announcement and tutorials
- [ ] Additional shell commands based on user feedback
- [ ] Support for Python/TypeScript code execution (exploring)
- [ ] Authentication and enterprise features

## FAQ

**Q: Why shell scripting instead of code mode (Python/TypeScript)?**

A: Shell pipelines are more natural for data transformation tasks and agents already know how to use them. However, code mode could be complementary for different use cases.

**Q: How does this compare to agents making individual tool calls?**

A: A task requiring 7 tool calls becomes 1 pipeline call, reducing tokens by 50%+ and eliminating the need to load all intermediate data into context.

**Q: Does this work with my existing MCP servers?**

A: Yes! MCP Shell coordinates any standard MCP servers running through ToolHive.

**Q: What about authentication?**

A: This is an open question. Currently relies on ToolHive's authentication model for connected MCP servers.

## Contributing

This is an experimental project. Contributions, ideas, and feedback are welcome!

## License

[To be determined]

## Credits

Developed by Dániel Kántor at ToolHive. Presented at Engineering Demo Day, October 2025.

---

**Note**: This is an experimental project exploring new patterns for AI agent coordination. The approach has proven effective in demos but needs broader testing and community feedback.
