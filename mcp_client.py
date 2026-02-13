import asyncio
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

# Default timeout for tool calls (30 seconds)
# This prevents tool calls from hanging forever if a server is unresponsive
DEFAULT_TOOL_TIMEOUT = 30.0


def _is_running_in_docker() -> bool:
    """Check if we're running inside a Docker container.

    Checks the RUNNING_IN_DOCKER environment variable (set in Dockerfile).
    """
    return os.getenv("RUNNING_IN_DOCKER") == "1"


class _TolerantStream(httpx.AsyncByteStream):
    """
    Stream wrapper that tolerates incomplete response errors.

    Some remote SSE servers (behind proxies/CDNs) close POST response connections
    before sending the complete response body. This is not a problem for SSE
    because the actual MCP response arrives via the SSE stream, not the POST response.
    """

    def __init__(self, original_stream: httpx.AsyncByteStream):
        self._original: httpx.AsyncByteStream = original_stream

    async def __aiter__(self):
        try:
            async for chunk in self._original:
                yield chunk
        except httpx.RemoteProtocolError:
            # Server closed connection before body was sent - this is OK
            # for SSE since the actual response comes via the SSE stream
            pass

    async def aclose(self):
        await self._original.aclose()


class _TolerantTransport(httpx.AsyncHTTPTransport):
    """
    Custom transport that tolerates servers closing POST response connections early.

    This is needed for some remote SSE MCP servers where the proxy/CDN closes
    the POST response connection before the body is fully sent. The actual MCP
    response arrives via SSE, so the POST response body is not needed.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)

        # For POST requests, wrap the stream to tolerate incomplete responses
        if request.method == "POST":
            original_stream = response.stream
            if isinstance(original_stream, httpx.AsyncByteStream):
                response.stream = _TolerantStream(original_stream)

        return response


def _create_tolerant_httpx_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """
    Create an httpx client that tolerates incomplete POST responses.

    This is needed for remote SSE MCP servers where the server/proxy closes
    the POST response connection before the body is sent. The actual MCP
    response arrives via SSE, so this is safe to ignore.
    """
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        transport=_TolerantTransport(),
    )


async def get_workloads(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> list[dict[str, Any]]:
    """
    Get list of workloads from ToolHive API.

    Also handles container networking by rewriting localhost URLs to use the
    actual ToolHive host, enabling inter-container communication.
    Only rewrites URLs when actually running in Docker to avoid breaking
    local runs (e.g. on macOS) when TOOLHIVE_HOST is set to host.docker.internal.
    """
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
        # Only replace when actually running in Docker to avoid breaking
        # local runs when TOOLHIVE_HOST is set to host.docker.internal
        if _is_running_in_docker() and host not in ("localhost", "127.0.0.1"):
            for workload in workloads:
                url = workload.get("url")
                if url:
                    parsed_url = urlparse(url)
                    workload_host = parsed_url.hostname

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
            async with sse_client(url, httpx_client_factory=_create_tolerant_httpx_client) as (read, write):
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

    except TimeoutError:
        return {
            "workload": name,
            "status": "error",
            "tools": [],
            "error": "Connection timed out",
        }
    except ExceptionGroup as eg:
        error_msg = _extract_error_from_exception_group(eg)
        return {"workload": name, "status": "error", "tools": [], "error": error_msg}
    except McpError as e:
        return {
            "workload": name,
            "status": "error",
            "tools": [],
            "error": f"MCP protocol error: {e}",
        }
    except Exception as e:
        import traceback

        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        return {"workload": name, "status": "error", "tools": [], "error": error_msg}


def _extract_error_from_exception_group(eg: ExceptionGroup) -> str:
    """Extract meaningful error message from ExceptionGroup (Python 3.13+)."""
    exceptions: list[BaseException] = []

    def collect_exceptions(exc_group: ExceptionGroup):
        for exc in exc_group.exceptions:
            if isinstance(exc, ExceptionGroup):
                collect_exceptions(exc)
            else:
                exceptions.append(exc)

    collect_exceptions(eg)

    # Look for McpError first, as it's the most specific
    for exc in exceptions:
        if isinstance(exc, McpError):
            return f"MCP protocol error: {exc}"

    # If no McpError found, return the first exception message
    if exceptions:
        first_exc = exceptions[0]
        return f"{type(first_exc).__name__}: {first_exc}"

    return str(eg)


async def get_tool_details_from_server(
    workload_name: str, tool_name: str, host: str | None = None, port: int | None = None
) -> dict[str, Any]:
    """Get detailed information about a specific tool from a workload"""
    # Discover ToolHive if not already done
    if host is None or port is None:
        from toolhive_client import discover_toolhive_async

        host, port = await discover_toolhive_async(host, port)

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
            async with sse_client(url, httpx_client_factory=_create_tolerant_httpx_client) as (read, write):
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
            from toolhive_client import discover_toolhive_async

            host, port = await discover_toolhive_async(host=None, port=None)
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
        async with sse_client(url, httpx_client_factory=_create_tolerant_httpx_client) as (read, write):
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
            from toolhive_client import discover_toolhive_async

            host, port = await discover_toolhive_async(host=None, port=None)
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
        async with sse_client(url, httpx_client_factory=_create_tolerant_httpx_client) as (read, write):
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
