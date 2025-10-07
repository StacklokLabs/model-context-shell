from fastmcp import FastMCP
import toolhive_client
import mcp_client


mcp = FastMCP("mcp-shell")


@mcp.tool()
def list_available_shell_commands() -> list[str]:
    """List basic, safe CLI commands commonly used in shell one-liners"""
    return [
        "grep",
        "jq",
        "curl",
        "sort",
        "uniq",
        "cut",
        "sed",
        "awk",
        "wc",
        "head",
        "tail",
        "tr",
        "echo",
        "printf",
        "date",
        "bc",
    ]


@mcp.tool()
def execute_pipeline(pipeline: list[dict]) -> str:
    """
    Execute a pipeline of tool calls and shell commands.

    Each item in the pipeline should be a dict with:
    - type: "tool" or "command"
    - For tool: name, server, args (optional)
    - For command: command

    Example:
    [
        {"type": "command", "command": "echo hello"},
        {"type": "tool", "name": "greet", "server": "mcp-example", "args": {"name": "world"}}
    ]
    """
    items = []
    for i, item in enumerate(pipeline):
        item_type = item.get("type")
        if item_type == "tool":
            name = item.get("name", "unknown")
            server = item.get("server", "unknown")
            items.append(f'tool "{name}" from server "{server}"')
        elif item_type == "command":
            command = item.get("command", "unknown")
            items.append(f'command "{command}"')
        else:
            items.append(f'unknown item type "{item_type}"')

    return f"Pipeline started with the following items: {', '.join(items)}"


@mcp.tool()
async def list_all_tools() -> str:
    """List all tools available from all MCP servers running through ToolHive"""
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

    # Initialize ToolHive client - starts thv serve and lists workloads
    toolhive_client.initialize()

    # Run the MCP server with HTTP transport
    # Check if --transport argument is provided
    transport = "streamable-http"  # Default to streamable-http for HTTP access
    port = 8000

    for i, arg in enumerate(sys.argv):
        if arg == "--transport" and i + 1 < len(sys.argv):
            transport = sys.argv[i + 1]
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        endpoint = "/sse" if transport == "sse" else "/mcp"
        print(f"\n🚀 Starting MCP server on http://localhost:{port}{endpoint}")
        print(f"   Transport: {transport}")
        print(f"   Connect via: http://localhost:{port}{endpoint}\n")
        mcp.run(transport=transport, port=port)
