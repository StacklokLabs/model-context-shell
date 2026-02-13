import asyncio
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

# Default timeout for tool calls (30 seconds)
# This prevents tool calls from hanging forever if a server is unresponsive
DEFAULT_TOOL_TIMEOUT = 30.0


async def get_workloads(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> list[dict[str, Any]]:
    """
    Get list of workloads from ToolHive API.

    Also handles container networking by rewriting localhost URLs to use the
    actual ToolHive host, enabling inter-container communication.
    """
    from urllib.parse import urlparse

    base_url = f"http://{host}:{port}"
    endpoint = "/api/v1beta/workloads"

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Force fresh data with cache-busting headers
        headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
        response = await client.get(f"{base_url}{endpoint}", headers=headers)
        response.raise_for_status()
        data = response.json()
        workloads = data.get("workloads", [])

        # Fix container networking: rewrite localhost URLs
        # When running in a container, URLs with 'localhost' or '127.0.0.1'
        # won't work for inter-container communication
        for workload in workloads:
            url = workload.get("url")
            if url:
                parsed_url = urlparse(url)
                workload_host = parsed_url.hostname

                # If the workload uses localhost, replace with actual ToolHive host
                if workload_host in ("localhost", "127.0.0.1"):
                    workload["url"] = url.replace(workload_host, host)

        return workloads


async def list_tools_from_server(workload: dict[str, Any]) -> dict[str, Any]:
    """List tools from a single MCP server workload"""
    name = workload.get("name", "unknown")

    # Tools that indicate this is mcp-shell itself (orchestrator, not a tool provider)
    # If a workload exposes these exact tools, it's likely us - filter it out
    ORCHESTRATOR_TOOLS = {
        "list_available_shell_commands",
        "execute_pipeline",
        "list_all_tools",
        "get_tool_details",
    }

    try:
        # Extract workload information
        transport_type = workload.get("transport_type", "")
        proxy_mode = workload.get("proxy_mode", "")
        url = workload.get("url", "")
        status = workload.get("status", "")

        # Only connect if the workload is running
        if status != "running":
            return {
                "workload": name,
                "status": "skipped",
                "tools": [],
                "error": f"Workload status is '{status}', not running",
            }

        if not url:
            return {
                "workload": name,
                "status": "error",
                "tools": [],
                "error": "No URL provided for workload",
            }

        # Determine which client to use based on proxy_mode or transport_type
        # ToolHive can proxy servers via SSE even if the original transport is stdio
        if proxy_mode == "sse":
            # Use SSE client for SSE proxy
            async with sse_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_response = await session.list_tools()
                    tools_info = [
                        {"name": tool.name, "description": tool.description or ""}
                        for tool in tools_response.tools
                    ]

                    # Check if this workload is mcp-shell itself
                    tool_names = {tool["name"] for tool in tools_info}
                    if ORCHESTRATOR_TOOLS.issubset(tool_names):
                        # This is us - skip to avoid self-reference
                        return {
                            "workload": name,
                            "status": "skipped",
                            "tools": [],
                            "error": "Skipped: orchestrator workload (self)",
                        }

                    return {
                        "workload": name,
                        "status": "success",
                        "tools": tools_info,
                        "error": None,
                    }
        elif proxy_mode == "streamable-http" or transport_type == "streamable-http":
            # Use streamable HTTP client
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_response = await session.list_tools()
                    tools_info = [
                        {"name": tool.name, "description": tool.description or ""}
                        for tool in tools_response.tools
                    ]

                    # Check if this workload is mcp-shell itself
                    tool_names = {tool["name"] for tool in tools_info}
                    if ORCHESTRATOR_TOOLS.issubset(tool_names):
                        # This is us - skip to avoid self-reference
                        return {
                            "workload": name,
                            "status": "skipped",
                            "tools": [],
                            "error": "Skipped: orchestrator workload (self)",
                        }

                    return {
                        "workload": name,
                        "status": "success",
                        "tools": tools_info,
                        "error": None,
                    }
        else:
            return {
                "workload": name,
                "status": "unsupported",
                "tools": [],
                "error": f"Transport/proxy mode '{proxy_mode or transport_type}' not yet supported",
            }

    except Exception as e:
        import traceback

        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        return {"workload": name, "status": "error", "tools": [], "error": error_msg}


async def get_tool_details_from_server(
    workload_name: str, tool_name: str, host: str | None = None, port: int | None = None
) -> dict[str, Any]:
    """Get detailed information about a specific tool from a workload"""
    # Discover ToolHive if not already done
    if host is None or port is None:
        from toolhive_client import discover_toolhive

        host, port = discover_toolhive(host, port)

    # Get workload details
    workloads = await get_workloads(host, port)
    workload = next((w for w in workloads if w.get("name") == workload_name), None)

    if not workload:
        return {"error": f"Workload '{workload_name}' not found"}

    try:
        transport_type = workload.get("transport_type", "")
        proxy_mode = workload.get("proxy_mode", "")
        url = workload.get("url", "")

        if not url:
            return {"error": "No URL provided for workload"}

        # Connect and list tools to find the requested tool
        if proxy_mode == "sse":
            async with sse_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_response = await session.list_tools()
                    tool = next(
                        (t for t in tools_response.tools if t.name == tool_name), None
                    )

                    if not tool:
                        return {
                            "error": f"Tool '{tool_name}' not found in workload '{workload_name}'"
                        }

                    return {
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.inputSchema,
                    }
        elif proxy_mode == "streamable-http" or transport_type == "streamable-http":
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_response = await session.list_tools()
                    tool = next(
                        (t for t in tools_response.tools if t.name == tool_name), None
                    )

                    if not tool:
                        return {
                            "error": f"Tool '{tool_name}' not found in workload '{workload_name}'"
                        }

                    return {
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.inputSchema,
                    }
        else:
            return {
                "error": f"Transport/proxy mode '{proxy_mode or transport_type}' not supported"
            }

    except Exception as e:
        import traceback

        return {
            "error": f"Failed to get tool details: {str(e)}\n{traceback.format_exc()}"
        }


async def call_tool(
    workload_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TOOL_TIMEOUT,
) -> Any:
    """
    Call a tool from a specific MCP server workload.

    Returns the tool result or raises an exception on error.

    Args:
        workload_name: The MCP server/workload name
        tool_name: The name of the tool to call
        arguments: Arguments to pass to the tool
        host: ToolHive host
        port: ToolHive port
        timeout: Timeout in seconds for the tool call (default: DEFAULT_TOOL_TIMEOUT)

    Note: For multiple calls to the same tool, use batch_call_tool() instead
    to reuse a single connection and avoid connection overhead.
    """
    # Resolve ToolHive connection dynamically when using defaults
    # This makes it work in containers and local when thv serve chooses a dynamic port
    try:
        if host == DEFAULT_HOST and port == DEFAULT_PORT:
            from toolhive_client import discover_toolhive

            host, port = discover_toolhive(host=None, port=None)
    except Exception:
        # Fall back to provided/defaults if discovery fails
        pass

    # Get the workload details
    workloads = await get_workloads(host, port)
    workload = next((w for w in workloads if w.get("name") == workload_name), None)

    if not workload:
        raise ValueError(f"Workload '{workload_name}' not found")

    url = workload.get("url", "")
    status = workload.get("status", "")
    proxy_mode = workload.get("proxy_mode", "")
    transport_type = workload.get("transport_type", "")

    if status != "running":
        raise RuntimeError(
            f"Workload '{workload_name}' is not running (status: {status})"
        )

    if not url:
        raise ValueError(f"No URL provided for workload '{workload_name}'")

    # Connect and call the tool with timeout
    if proxy_mode == "sse":
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=arguments),
                    timeout=timeout,
                )
                return result
    elif proxy_mode == "streamable-http" or transport_type == "streamable-http":
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=arguments),
                    timeout=timeout,
                )
                return result
    else:
        raise ValueError(
            f"Transport/proxy mode '{proxy_mode or transport_type}' not supported"
        )


async def batch_call_tool(
    workload_name: str,
    tool_name: str,
    arguments_list: list[dict[str, Any]],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TOOL_TIMEOUT,
) -> list[Any]:
    """
    Call a tool multiple times using a single connection.

    This is much more efficient than calling call_tool() in a loop, as it
    reuses the same MCP session for all calls, avoiding the overhead of:
    - HTTP connection setup per call
    - MCP session initialization per call
    - Workload discovery per call

    Args:
        workload_name: The MCP server/workload name
        tool_name: The name of the tool to call
        arguments_list: List of argument dicts, one per call
        host: ToolHive host
        port: ToolHive port
        timeout: Timeout in seconds for each individual tool call (default: DEFAULT_TOOL_TIMEOUT)

    Returns:
        List of tool results in the same order as arguments_list
    """
    if not arguments_list:
        return []

    # Resolve ToolHive connection dynamically when using defaults
    try:
        if host == DEFAULT_HOST and port == DEFAULT_PORT:
            from toolhive_client import discover_toolhive

            host, port = discover_toolhive(host=None, port=None)
    except Exception:
        # Fall back to provided/defaults if discovery fails
        pass

    # Get the workload details (only once for all calls)
    workloads = await get_workloads(host, port)
    workload = next((w for w in workloads if w.get("name") == workload_name), None)

    if not workload:
        raise ValueError(f"Workload '{workload_name}' not found")

    url = workload.get("url", "")
    status = workload.get("status", "")
    proxy_mode = workload.get("proxy_mode", "")
    transport_type = workload.get("transport_type", "")

    if status != "running":
        raise RuntimeError(
            f"Workload '{workload_name}' is not running (status: {status})"
        )

    if not url:
        raise ValueError(f"No URL provided for workload '{workload_name}'")

    # Connect once and call the tool multiple times with timeout per call
    results = []
    total_items = len(arguments_list)

    async def execute_calls(session):
        nonlocal results
        for idx, arguments in enumerate(arguments_list):
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=arguments),
                    timeout=timeout,
                )
                results.append(result)
            except Exception as e:
                # Build informative error message with progress info
                completed = len(results)
                pending = total_items - idx - 1
                failed_item = idx + 1  # 1-indexed for user-friendly message

                # Extract partial results text for context
                partial_results_text = []
                for r in results:
                    if hasattr(r, "content"):
                        for content_item in r.content:
                            if hasattr(content_item, "text"):
                                partial_results_text.append(content_item.text)
                    else:
                        partial_results_text.append(str(r))

                error_parts = [
                    f"Batch tool call failed at item {failed_item} of {total_items}.",
                    f"Completed: {completed} successful, {pending} pending.",
                    f"Error: {str(e)}",
                ]

                if partial_results_text:
                    error_parts.append(
                        "Partial results from successful calls:\n"
                        + "\n".join(partial_results_text)
                    )

                raise RuntimeError("\n".join(error_parts)) from e

    if proxy_mode == "sse":
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await execute_calls(session)
    elif proxy_mode == "streamable-http" or transport_type == "streamable-http":
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await execute_calls(session)
    else:
        raise ValueError(
            f"Transport/proxy mode '{proxy_mode or transport_type}' not supported"
        )

    return results


async def list_tools(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> list[dict[str, Any]]:
    """
    List tools from all MCP servers running through ToolHive.

    Returns a list of dictionaries, each containing:
    - workload: name of the workload
    - status: status of the connection attempt
    - tools: list of tools available from that server
    - error: error message if connection failed
    """
    try:
        # Get all workloads
        workloads = await get_workloads(host, port)

        if not workloads:
            return []

        # Query each workload concurrently
        tasks = [list_tools_from_server(workload) for workload in workloads]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions that occurred
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    {
                        "workload": workloads[i].get("name", f"workload_{i}"),
                        "status": "error",
                        "tools": [],
                        "error": str(result),
                    }
                )
            else:
                processed_results.append(result)

        return processed_results

    except Exception as e:
        # If we can't even get the workload list, return error
        return [
            {
                "workload": "toolhive",
                "status": "error",
                "tools": [],
                "error": f"Failed to get workload list: {str(e)}",
            }
        ]
