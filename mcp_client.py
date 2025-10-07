import asyncio
from typing import List, Dict, Any
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


async def get_workloads(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> List[Dict[str, Any]]:
    """Get list of workloads from ToolHive API"""
    base_url = f"http://{host}:{port}"
    endpoint = "/api/v1beta/workloads"

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Force fresh data with cache-busting headers
        headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
        response = await client.get(f"{base_url}{endpoint}", headers=headers)
        response.raise_for_status()
        data = response.json()
        # API returns {"workloads": [...]} so extract the list
        return data.get("workloads", [])


async def list_tools_from_server(workload: Dict[str, Any]) -> Dict[str, Any]:
    """List tools from a single MCP server workload"""
    name = workload.get("name", "unknown")

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
                "error": f"Workload status is '{status}', not running"
            }

        if not url:
            return {
                "workload": name,
                "status": "error",
                "tools": [],
                "error": "No URL provided for workload"
            }

        # Determine which client to use based on proxy_mode or transport_type
        # ToolHive can proxy servers via SSE even if the original transport is stdio
        if proxy_mode == "sse":
            # Use SSE client for SSE proxy
            async with sse_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_response = await session.list_tools()
                    tool_names = [tool.name for tool in tools_response.tools]
                    return {
                        "workload": name,
                        "status": "success",
                        "tools": tool_names,
                        "error": None
                    }
        elif proxy_mode == "streamable-http" or transport_type == "streamable-http":
            # Use streamable HTTP client
            async with streamablehttp_client(url) as (read, write, get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_response = await session.list_tools()
                    tool_names = [tool.name for tool in tools_response.tools]
                    return {
                        "workload": name,
                        "status": "success",
                        "tools": tool_names,
                        "error": None
                    }
        else:
            return {
                "workload": name,
                "status": "unsupported",
                "tools": [],
                "error": f"Transport/proxy mode '{proxy_mode or transport_type}' not yet supported"
            }

    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        return {
            "workload": name,
            "status": "error",
            "tools": [],
            "error": error_msg
        }


async def list_tools(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> List[Dict[str, Any]]:
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
                processed_results.append({
                    "workload": workloads[i].get("name", f"workload_{i}"),
                    "status": "error",
                    "tools": [],
                    "error": str(result)
                })
            else:
                processed_results.append(result)

        return processed_results

    except Exception as e:
        # If we can't even get the workload list, return error
        return [{
            "workload": "toolhive",
            "status": "error",
            "tools": [],
            "error": f"Failed to get workload list: {str(e)}"
        }]
