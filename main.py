from fastmcp import FastMCP
import toolhive_client

mcp = FastMCP("hello-world")


@mcp.tool()
def greet(name: str) -> str:
    """Greet a person by name"""
    return f"Hello, {name}!"


if __name__ == "__main__":
    # Initialize ToolHive client - starts thv serve and lists workloads
    toolhive_client.initialize()

    # Run the MCP server
    mcp.run()
