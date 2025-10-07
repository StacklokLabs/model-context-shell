from fastmcp import FastMCP
import toolhive_client
import mcp_client


mcp = FastMCP("mcp-shell")


@mcp.tool()
def greet(name: str) -> str:
    """Greet a person by name"""
    return f"Hello, {name}!"


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
    transport = "sse"  # Default to SSE for HTTP access
    port = 8000

    for i, arg in enumerate(sys.argv):
        if arg == "--transport" and i + 1 < len(sys.argv):
            transport = sys.argv[i + 1]
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        print(f"\n🚀 Starting MCP server on http://localhost:{port}/sse")
        print(f"   Transport: {transport}")
        print(f"   Connect via: http://localhost:{port}/sse\n")
        mcp.run(transport=transport, port=port)
