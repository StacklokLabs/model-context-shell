from fastmcp import FastMCP
import toolhive_client
import mcp_client
import subprocess
import threading
from typing import Iterable, Generator
import asyncio
import json


mcp = FastMCP("mcp-shell")


# Whitelist of allowed shell commands
ALLOWED_COMMANDS = [
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


def validate_command(cmd: str) -> None:
    """Validate that a command only uses allowed commands."""
    # Extract the first word (the actual command)
    command_parts = cmd.strip().split()
    if not command_parts:
        raise ValueError("Empty command")

    base_command = command_parts[0]

    # Check if it's in the allowed list
    if base_command not in ALLOWED_COMMANDS:
        raise ValueError(
            f"Command '{base_command}' is not allowed. "
            f"Allowed commands: {', '.join(ALLOWED_COMMANDS)}"
        )


def shell_stage(cmd: str, upstream: Iterable[str], for_each: bool = False) -> Generator[str, None, None]:
    """Run a shell command as a streaming stage, consuming upstream lazily."""

    if for_each:
        # Execute command once per input line
        input_data = "".join(upstream)
        for line in input_data.strip().split('\n'):
            if not line.strip():
                continue

            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Write single line and get output
            stdout, _ = proc.communicate(input=line + '\n')
            for output_line in stdout.splitlines(keepends=True):
                yield output_line
    else:
        # Execute command once with all input (streaming)
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

        # Like shell pipelines, we don't fail on non-zero exit codes
        # The pipeline continues and only breaks on severe errors (handled by exceptions above)


async def tool_stage(server: str, tool: str, args: dict, upstream: Iterable[str], for_each: bool = False) -> str:
    """Call an MCP tool with upstream data as input."""

    if for_each:
        # Execute tool once per line (expecting JSONL input)
        results = []
        input_data = "".join(upstream)

        for line in input_data.strip().split('\n'):
            if not line.strip():
                continue

            try:
                # Parse each line as JSON
                parsed_line = json.loads(line)
                # Merge with args (args take precedence)
                if isinstance(parsed_line, dict):
                    call_args = {**parsed_line, **args}
                else:
                    call_args = {**args, "input": parsed_line}
            except json.JSONDecodeError:
                # If parsing fails, use as string input
                call_args = {**args, "input": line}

            # Call the tool
            result = await mcp_client.call_tool(server, tool, call_args)

            # Extract content from result
            if hasattr(result, 'content'):
                for content_item in result.content:
                    if hasattr(content_item, 'text'):
                        results.append(content_item.text)
            else:
                results.append(str(result))

        return '\n'.join(results)

    else:
        # Execute tool once with all upstream data
        # Collect all upstream data
        input_data = "".join(upstream).strip()

        # If there's upstream data, try to parse it as JSON and merge with args
        if input_data:
            try:
                parsed_input = json.loads(input_data)
                # If parsed input is a dict, merge it with args (args take precedence)
                if isinstance(parsed_input, dict):
                    args = {**parsed_input, **args}
                else:
                    # If it's not a dict (e.g., array, string), add as 'input' field
                    if "input" not in args:
                        args = {**args, "input": parsed_input}
            except json.JSONDecodeError:
                # If JSON parsing fails, treat as plain string input
                if "input" not in args:
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
    """
    List basic, safe CLI commands commonly used in shell one-liners.

    These commands are available for use in execute_pipeline for data transformation:
    - jq: JSON processing and transformation (essential for API data)
    - grep: Text filtering and pattern matching
    - sed/awk: Advanced text processing
    - sort/uniq: Data organization
    - curl: HTTP requests

    Use these in pipelines for precise data manipulation between tool calls.
    """
    return ALLOWED_COMMANDS


@mcp.tool()
async def execute_pipeline(pipeline: list[dict], initial_input: str = "") -> str:
    """
    Execute a pipeline of tool calls and shell commands.

    ⚠️ IMPORTANT: You should STRONGLY PREFER using pipelines for:
    - Any coordinated sequence of tool calls (2+ tools working together)
    - Data extraction, transformation, or mining tasks
    - Tasks requiring data accuracy and precise filtering
    - Complex data processing workflows
    - Any scenario where you need to transform data between tool calls

    Pipelines provide superior data accuracy through:
    - Shell commands like jq for precise JSON manipulation
    - grep/sed/awk for text processing
    - Streaming data between stages without data loss
    - Ability to inspect and transform data at each stage

    Each item in the pipeline should be a dict with:
    - type: "tool" or "command"
    - for_each: (optional) if true, runs the stage once per input line
    - For tool: name, server, args (optional)
    - For command: command

    Example - Fetch and process API data:
    [
        {"type": "tool", "name": "fetch", "server": "fetch", "args": {"url": "https://api.example.com/data"}},
        {"type": "command", "command": "jq '.items[] | {id, name}'"},
        {"type": "command", "command": "grep -i 'search_term'"}
    ]

    Example - Process multiple items with for_each:
    [
        {"type": "command", "command": "jq -c '.[]'"},  // Convert array to JSONL
        {"type": "tool", "name": "fetch", "server": "fetch", "for_each": true}  // Call once per line
    ]

    When for_each is true:
    - Commands run once per input line
    - Tools expect JSONL input and parse each line as JSON
    """
    try:
        # Start with initial input as a generator
        upstream: Iterable[str] = iter([initial_input]) if initial_input else iter([])

        # Process each stage in the pipeline
        for idx, item in enumerate(pipeline):
            item_type = item.get("type")
            for_each = item.get("for_each", False)

            if item_type == "command":
                command = item.get("command", "")
                if not command:
                    raise ValueError("Command stage missing 'command' field")
                try:
                    # Validate command before execution
                    validate_command(command)
                    upstream = shell_stage(command, upstream, for_each=for_each)
                except Exception as e:
                    raise RuntimeError(f"Stage {idx + 1} (command) failed: {str(e)}")

            elif item_type == "tool":
                tool_name = item.get("name", "")
                server_name = item.get("server", "")
                args = item.get("args", {})

                if not tool_name:
                    raise ValueError("Tool stage missing 'name' field")
                if not server_name:
                    raise ValueError("Tool stage missing 'server' field")

                try:
                    # Tool stages consume all upstream and return a result
                    result = await tool_stage(server_name, tool_name, args, upstream, for_each=for_each)
                    # Convert result back to a stream for next stage
                    # Ensure result ends with newline for proper shell command processing
                    if result and not result.endswith('\n'):
                        result += '\n'
                    upstream = iter([result])
                except Exception as e:
                    raise RuntimeError(f"Stage {idx + 1} (tool {server_name}/{tool_name}) failed: {str(e)}")

            else:
                raise ValueError(f"Unknown pipeline item type: {item_type}")

        # Collect final output
        output = "".join(upstream)
        return output

    except Exception as e:
        import traceback
        error_details = f"Pipeline execution failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        return error_details


@mcp.tool()
async def list_all_tools() -> str:
    """
    List all tools available from all MCP servers running through ToolHive.

    Use this to discover available tools, then use execute_pipeline to coordinate multiple tool calls
    for data processing, transformation, and mining tasks where accuracy is critical.
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
