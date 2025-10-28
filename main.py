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
async def execute_pipeline(pipeline: list[dict]) -> str:
    """
    Execute a pipeline of tool calls and shell commands to coordinate multiple operations.

    ⚠️ IMPORTANT: Before using this tool, call list_all_tools() to discover what tools
    are actually available. Do not assume tools exist - verify them first!

    A pipeline chains multiple stages where data flows from one to the next:
    - Tool stages: Call external tools (from list_all_tools)
    - Command stages: Transform data with jq, grep, sed, awk, etc.

    Pipeline Structure:
    Each stage is a dict with:
    - type: "tool" | "command"
    - for_each (optional): Process items one-by-one instead of all at once

    Tool Stage:
    {"type": "tool", "name": "tool_name", "server": "server_name", "args": {...}}
    - Calls a tool from an MCP server (get names from list_all_tools)
    - Automatically merges upstream JSON data with args before calling tool
    - ⚠️ If upstream has extra fields the tool doesn't accept, use jq to filter first

    Command Stage:
    {"type": "command", "command": "jq", "args": ["-c", ".field"]}
    - Runs whitelisted shell commands (see list_available_shell_commands)
    - Command and args MUST be separate (security requirement)

    Example - Chain tools with data transformation:
    [
        {"type": "tool", "name": "get_data", "server": "database", "args": {"table": "users"}},
        {"type": "command", "command": "jq", "args": ["-c", ".[] | select(.active == true)"]},
        {"type": "tool", "name": "send_notification", "server": "notifications", "args": {"channel": "admin"}}
    ]

    Example - Process multiple items with for_each:
    [
        {"type": "tool", "name": "list_users", "server": "api", "args": {}},
        {"type": "command", "command": "jq", "args": ["-c", ".users[] | {user_id: .id}"]},
        {"type": "tool", "name": "get_profile", "server": "api", "for_each": true}
    ]

    How for_each works:
    - Requires JSONL input (one JSON object per line from jq)
    - Calls the tool once per line, collecting all results into an array
    - IMPORTANT: Use jq to extract ONLY the fields the tool accepts
      Example: If get_profile only accepts {user_id: "..."}, use jq to create that exact structure
      This avoids "unexpected additional properties" errors from automatic merging

    Best Practices:
    - Build complete workflows as single pipelines (don't split unnecessarily)
    - Check list_all_tools first to see what's available
    - Use get_tool_details(server, tool_name) to see exact tool parameters/schema
    - Use jq to filter data to match the tool's expected fields (prevents schema errors)
    - Use for_each to process collections item-by-item (results collected into array)
    """
    return await engine.execute_pipeline(pipeline)


async def _list_all_tools_impl() -> str:
    """Implementation of list_all_tools (extracted for testing)"""
    tools_list = await mcp_client.list_tools()

    if not tools_list:
        return "No MCP servers found"

    result = []
    for server in tools_list:
        workload = server.get("workload", "unknown")
        status = server.get("status", "unknown")
        tools = server.get("tools", [])
        error = server.get("error")

        # Skip self-reference workloads (orchestrator)
        if status == "skipped" and error and "orchestrator" in error:
            continue

        result.append(f"\n**{workload}**")
        result.append(f"  Status: {status}")

        if tools:
            for tool in tools:
                if isinstance(tool, dict):
                    tool_name = tool.get("name", "unknown")
                    description = tool.get("description", "")
                    # Truncate description: replace newlines with spaces, limit to 200 chars
                    if description:
                        description = description.replace("\n", " ").replace("\r", " ")
                        if len(description) > 200:
                            description = description[:200] + "..."
                        result.append(f"  - {tool_name}: {description}")
                    else:
                        result.append(f"  - {tool_name}")
                else:
                    # Backwards compatibility: if tools is just a list of names
                    result.append(f"  - {tool}")

        if error:
            result.append(f"  Error: {error}")

    return "\n".join(result)


@mcp.tool()
async def list_all_tools() -> str:
    """
    List all tools available from all MCP servers running through ToolHive.

    Shows tool names with brief descriptions. Use get_tool_details() to see full descriptions
    and parameter schemas for a specific tool.

    Use execute_pipeline to coordinate multiple tool calls for data processing workflows.
    """
    return await _list_all_tools_impl()


async def _get_tool_details_impl(server: str, tool_name: str) -> str:
    """Implementation of get_tool_details (extracted for testing)"""
    import json

    details = await mcp_client.get_tool_details_from_server(server, tool_name)

    if "error" in details:
        return f"Error: {details['error']}"

    result = []
    result.append(f"Tool: {details.get('name', 'unknown')}")
    result.append(f"\nDescription:\n{details.get('description', 'No description available')}")
    result.append(f"\nInput Schema:")
    result.append(json.dumps(details.get('inputSchema', {}), indent=2))

    return "\n".join(result)


@mcp.tool()
async def get_tool_details(server: str, tool_name: str) -> str:
    """
    Get detailed information about a specific tool including its full description and parameter schema.

    Args:
        server: The MCP server/workload name (e.g., "fetch", "filesystem")
        tool_name: The name of the tool to get details for

    Returns detailed information including:
    - Full description
    - Input schema (JSON Schema describing required and optional parameters)
    """
    return await _get_tool_details_impl(server, tool_name)


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
