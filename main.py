from fastmcp import FastMCP
import toolhive_client
import mcp_client
import subprocess
import threading
from typing import Iterable, Generator
import asyncio
import json


mcp = FastMCP("mcp-shell")


def shell_stage(cmd: str, upstream: Iterable[str]) -> Generator[str, None, None]:
    """Run a shell command as a streaming stage, consuming upstream lazily."""
    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    assert proc.stdin and proc.stdout

    # Write upstream into the process stdin in the background
    def _writer():
        try:
            for item in upstream:
                proc.stdin.write(item)
            proc.stdin.close()
        except BrokenPipeError:
            pass

    threading.Thread(target=_writer, daemon=True).start()

    # Yield stdout as it arrives
    for line in proc.stdout:
        yield line

    rc = proc.wait()
    if rc != 0:
        stderr_output = proc.stderr.read() if proc.stderr else ""
        raise subprocess.CalledProcessError(rc, cmd, stderr=stderr_output)


async def tool_stage(server: str, tool: str, args: dict, upstream: Iterable[str]) -> str:
    """Call an MCP tool with upstream data as input."""
    # Collect all upstream data
    input_data = "".join(upstream)

    # Add input_data to args if not already present
    if "input" not in args and input_data:
        args = {**args, "input": input_data}

    # Call the tool
    result = await mcp_client.call_tool(server, tool, args)

    # Extract content from result
    if hasattr(result, 'content'):
        for content_item in result.content:
            if hasattr(content_item, 'text'):
                return content_item.text

    # Fallback to string representation
    return str(result)


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
async def execute_pipeline(pipeline: list[dict], initial_input: str = "") -> str:
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
    try:
        # Start with initial input as a generator
        upstream: Iterable[str] = iter([initial_input]) if initial_input else iter([])

        # Process each stage in the pipeline
        for item in pipeline:
            item_type = item.get("type")

            if item_type == "command":
                command = item.get("command", "")
                if not command:
                    raise ValueError("Command stage missing 'command' field")
                upstream = shell_stage(command, upstream)

            elif item_type == "tool":
                tool_name = item.get("name", "")
                server_name = item.get("server", "")
                args = item.get("args", {})

                if not tool_name:
                    raise ValueError("Tool stage missing 'name' field")
                if not server_name:
                    raise ValueError("Tool stage missing 'server' field")

                # Tool stages consume all upstream and return a result
                result = await tool_stage(server_name, tool_name, args, upstream)
                # Convert result back to a stream for next stage
                upstream = iter([result])

            else:
                raise ValueError(f"Unknown pipeline item type: {item_type}")

        # Collect final output
        output = "".join(upstream)
        return output

    except Exception as e:
        return f"Pipeline execution failed: {str(e)}"


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
