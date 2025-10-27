from fastmcp import FastMCP
import toolhive_client
import mcp_client
from shell_engine import ShellEngine
import os


mcp = FastMCP(
    "model-context-shell",
    instructions="""
    This MCP server provides pipeline execution for coordinating tool calls and shell commands.

    KEY PRINCIPLE: Build complete workflows as SINGLE pipeline calls. Don't make multiple
    execute_pipeline calls where you manually copy/paste data between them. Instead, construct
    the entire workflow in one pipeline and use jq/grep/sed to transform data between stages.

    Only inspect intermediate results to verify correctness, not to manually pass data around.
    """
)


# Create the shell engine with MCP client's call_tool as the tool caller
# This uses dependency injection to decouple the engine from MCP specifics
engine = ShellEngine(tool_caller=mcp_client.call_tool)


@mcp.tool()
def list_available_shell_commands() -> list[str]:
    """
    List basic, safe CLI commands commonly used in shell one-liners.

    These commands are available for use in execute_pipeline for data transformation:
    - jq: JSON processing and transformation (essential for API data)
    - grep: Text filtering and pattern matching
    - sed/awk: Advanced text processing
    - sort/uniq: Data organization

    ⚠️ SECURITY: In pipelines, specify command name and args separately:
    {"type": "command", "command": "jq", "args": ["-c", ".foo"]}
    NOT: {"type": "command", "command": "jq -c .foo"}

    Use these in pipelines for precise data manipulation between tool calls.
    """
    return engine.list_available_commands()


@mcp.tool()
async def execute_pipeline(pipeline: list[dict], initial_input: str = "") -> str:
    """
    Execute a pipeline of tool calls and shell commands.

    ⚠️ CRITICAL: You should STRONGLY PREFER using pipelines for:
    - Any coordinated sequence of tool calls (2+ tools working together)
    - Data extraction, transformation, or mining tasks
    - Tasks requiring data accuracy and precise filtering
    - Complex data processing workflows
    - Any scenario where you need to transform data between tool calls

    ⚠️ CRITICAL WORKFLOW PATTERN - Build Complete Pipelines:
    - Construct the ENTIRE workflow as a SINGLE pipeline call
    - DO NOT manually copy data from one execute_pipeline result into another
    - DO NOT make multiple execute_pipeline calls when one would suffice
    - Use jq/grep/sed/awk WITHIN the pipeline to transform data between stages
    - Only inspect intermediate results to VERIFY correctness, not to manually pass data
    - The pipeline automatically streams data between stages - leverage this!

    Example of CORRECT approach (single pipeline):
    execute_pipeline([
        {"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "..."}},
        {"type": "command", "command": "jq", "args": ["-c", ".items[] | {id, url}"]},
        {"type": "tool", "name": "process", "server": "processor", "for_each": true}
    ])

    Example of WRONG approach (multiple calls with manual data passing):
    # DON'T DO THIS:
    result1 = execute_pipeline([{"type": "tool", "name": "fetch", ...}])
    # Then manually parse result1 in your context and construct result2
    result2 = execute_pipeline([{"type": "tool", "name": "process", "args": {"data": result1}}])

    Pipelines provide superior data accuracy through:
    - Shell commands like jq for precise JSON manipulation
    - grep/sed/awk for text processing
    - Streaming data between stages without data loss
    - Automatic data flow - no manual copying needed

    Each item in the pipeline should be a dict with:
    - type: "tool", "command", or "read_buffers"
    - for_each: (optional) if true, runs the stage once per input line
    - save_to: (optional) save stage output to a named buffer for later retrieval
    - For tool: name, server, args (optional dict)
    - For command: command (string), args (optional array of strings)
    - For read_buffers: buffers (array of buffer names to retrieve)

    Example - Fetch and process API data:
    [
        {"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "https://api.example.com/data"}},
        {"type": "command", "command": "jq", "args": [".items[] | {id, name}"]},
        {"type": "command", "command": "grep", "args": ["-i", "search_term"]}
    ]

    Example - Fetch multiple URLs with for_each:
    [
        {"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "https://swapi.dev/api/people/1/"}},
        {"type": "command", "command": "jq", "args": ["-c", ".films[] | {url: .}"]},  // Convert URLs to JSONL
        {"type": "tool", "name": "fetch", "server": "fetch", "for_each": true},  // Fetch each URL
        {"type": "command", "command": "jq", "args": ["-s", "sort_by(.release_date)"]}  // Sort results
    ]

    Example - Using buffers to save intermediate results:
    [
        {"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "..."}, "save_to": "raw_data"},
        {"type": "command", "command": "jq", "args": [".items[]"], "save_to": "items"},
        {"type": "command", "command": "jq", "args": ["length"]},  // Continue processing
        {"type": "read_buffers", "buffers": ["raw_data", "items"]}  // Retrieve saved buffers as JSON
    ]
    // read_buffers returns: {"raw_data": "...", "items": "..."}

    Example - Dynamic tool parameters via jq (for bulk APIs):
    [
        {"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "https://api.com/country/DEU"}},
        {"type": "command", "command": "jq", "args": ["-c",
            "{url: \"https://api.com/bulk?codes=\\(.[0].borders | join(\",\"))\"}"]},
        {"type": "tool", "name": "fetch", "server": "fetch"}  // Gets {"url": "..."} via JSON merging
    ]
    // jq constructs the full parameter object, tool receives it automatically

    Example - Process items individually with for_each:
    [
        {"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "https://api.com/country/DEU"}},
        {"type": "command", "command": "jq", "args": ["-c", ".[0].borders[] | {url: \"https://api.com/\\(.)\"}"]},
        {"type": "tool", "name": "fetch", "server": "fetch", "for_each": true}  // Fetches each individually
    ]
    // for_each processes one item per line - scales to any number of items

    ⚠️ CRITICAL - Command Security:
    - Command name and arguments MUST be separate fields
    - Command: string (e.g., "jq"), Args: array of strings (e.g., ["-c", ".foo"])
    - This prevents shell injection attacks by using shell=False
    - Never try to combine them into a single string

    ⚠️ CRITICAL - Dynamic tool parameters:
    - Use jq to construct tool parameter objects dynamically
    - Tools automatically merge JSON objects from stdin with their args
    - For bulk operations: jq creates single object with all data
    - For individual items: jq creates JSONL (one object per line) + use for_each
    - This enables complex workflows in a single pipeline without manual copying

    ⚠️ CRITICAL for for_each with tools:
    - Tools with for_each REQUIRE properly structured JSONL input
    - Each line must be a JSON object with the correct parameter names for that tool
    - Example: fetch tool needs {"url": "..."} not just "https://..."
    - Use jq to transform plain values into objects: {"command": "jq", "args": ["-c", ".[] | {url: .}"]}

    When for_each is true:
    - Commands run once per input line (can be plain text)
    - Tools run once per line with JSONL input (MUST be properly structured JSON objects)
    """
    return await engine.execute_pipeline(pipeline, initial_input)


@mcp.tool()
async def list_all_tools() -> str:
    """
    List all tools available from all MCP servers running through ToolHive.

    Use this to discover available tools, then use execute_pipeline to coordinate multiple tool calls
    for data processing, transformation, and mining tasks where accuracy is critical.

    ⚠️ IMPORTANT: After discovering tools, build complete workflows as SINGLE pipeline calls.
    Don't make multiple execute_pipeline calls where you manually pass data between them.
    Instead, chain all operations together and use jq/grep/sed within the pipeline to transform data.
    """
    tools_list = await mcp_client.list_tools()

    if not tools_list:
        return "No MCP servers found"

    result = []
    for server in tools_list:
        workload = server.get("workload", "unknown")
        status = server.get("status", "unknown")
        tools = server.get("tools", [])
        error = server.get("error")

        result.append(f"\n**{workload}**")
        result.append(f"  Status: {status}")

        if tools:
            result.append(f"  Tools: {', '.join(tools)}")

        if error:
            result.append(f"  Error: {error}")

    return "\n".join(result)


if __name__ == "__main__":
    import sys
    import os

    # Check if running in container (ToolHive will manage thv serve)
    # If TOOLHIVE_HOST is set, we're in container mode and shouldn't start thv serve
    in_container = os.environ.get("TOOLHIVE_HOST") is not None

    if not in_container:
        # Local development mode: Initialize ToolHive client - starts thv serve and lists workloads
        toolhive_client.initialize()
    else:
        # Container mode: Skip ToolHive discovery during startup
        # Tools will be discovered dynamically when execute_pipeline is called
        print("Running in container mode - ToolHive connection will be established on first tool use\n")

    # Run the MCP server with HTTP transport
    # Check if --transport argument is provided
    transport = "streamable-http"  # Default to streamable-http for HTTP access
    port = 8000
    host = "0.0.0.0" if in_container else "127.0.0.1"  # Bind to 0.0.0.0 in container for external access

    for i, arg in enumerate(sys.argv):
        if arg == "--transport" and i + 1 < len(sys.argv):
            transport = sys.argv[i + 1]
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
        elif arg == "--host" and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        endpoint = "/sse" if transport == "sse" else "/mcp"
        print(f"\n🚀 Starting Model Context Shell on http://{host}:{port}{endpoint}")
        print(f"   Transport: {transport}")
        print(f"   Bind address: {host}")
        print(f"   Connect via: http://localhost:{port}{endpoint}\n")
        mcp.run(transport=transport, host=host, port=port)
