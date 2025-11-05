import subprocess
import atexit
import time
import asyncio
import httpx
import mcp_client
import os

# Global variable to hold the thv serve process
thv_process = None

# Default API configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_SCAN_PORT_START = 50000
DEFAULT_SCAN_PORT_END = 50100

# Global variables to store discovered connection info
_discovered_host = None
_discovered_port = None


def start_thv_serve():
    """Start the thv serve process"""
    global thv_process
    print("Starting thv serve...")
    thv_process = subprocess.Popen(
        ["thv", "serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(f"thv serve started with PID: {thv_process.pid}")

    # Give it a moment to start up
    time.sleep(1)


def stop_thv_serve():
    """Stop the thv serve process"""
    global thv_process
    if thv_process:
        print("Stopping thv serve...")
        thv_process.terminate()
        try:
            thv_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            thv_process.kill()
        print("thv serve stopped")


def _is_toolhive_available(host: str, port: int, timeout: float = 1.0) -> bool:
    """
    Check if ToolHive is available at the given host and port.

    Uses the /api/v1beta/version endpoint to verify ToolHive is running.
    """
    try:
        response = httpx.get(
            f"http://{host}:{port}/api/v1beta/version",
            timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
        # Verify it's actually ToolHive by checking for version field
        return "version" in data
    except Exception:
        return False


def _scan_for_toolhive(
    host: str,
    scan_port_start: int = DEFAULT_SCAN_PORT_START,
    scan_port_end: int = DEFAULT_SCAN_PORT_END
) -> int:
    """
    Scan for ToolHive in the specified port range.

    Returns the first port where ToolHive is found, or raises ConnectionError.
    """
    print(f"Scanning for ToolHive on {host} in port range {scan_port_start}-{scan_port_end}...")

    for port in range(scan_port_start, scan_port_end + 1):
        if _is_toolhive_available(host, port):
            print(f"✓ ToolHive found at {host}:{port}")
            return port

    raise ConnectionError(
        f"ToolHive not found on {host} in port range {scan_port_start}-{scan_port_end}. "
        f"Is 'thv serve' running?"
    )


def discover_toolhive(
    host: str = None,
    port: int = None,
    scan_port_start: int = DEFAULT_SCAN_PORT_START,
    scan_port_end: int = DEFAULT_SCAN_PORT_END,
    skip_port_discovery: bool = False
) -> tuple[str, int]:
    """
    Discover ToolHive connection parameters.

    This implements the same discovery algorithm as meta-mcp:
    1. Use explicit host/port if provided and working
    2. Fall back to scanning a port range
    3. Support skipping discovery for known environments (K8s)

    Args:
        host: ToolHive host (defaults to env TOOLHIVE_HOST or "127.0.0.1")
        port: ToolHive port (if None, will scan for it)
        scan_port_start: Start of port scan range
        scan_port_end: End of port scan range
        skip_port_discovery: Skip port scanning (useful in K8s with known ports)

    Returns:
        tuple of (host, port)
    """
    global _discovered_host, _discovered_port

    # Use cached values if available
    if _discovered_host and _discovered_port:
        return _discovered_host, _discovered_port

    # Get host from parameter, env, or default
    host = host or os.environ.get("TOOLHIVE_HOST", DEFAULT_HOST)

    # Handle port discovery
    if skip_port_discovery:
        port = port or DEFAULT_PORT
        print(f"Using ToolHive at {host}:{port} (port discovery skipped)")
    elif port is not None:
        # Try the provided port first
        if _is_toolhive_available(host, port):
            print(f"✓ ToolHive found at {host}:{port}")
        else:
            # Fall back to scanning
            print(f"Port {port} not available, scanning for ToolHive...")
            port = _scan_for_toolhive(host, scan_port_start, scan_port_end)
    else:
        # Scan for ToolHive
        port = _scan_for_toolhive(host, scan_port_start, scan_port_end)

    # Cache the discovered values
    _discovered_host = host
    _discovered_port = port

    return host, port


def list_workloads(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> dict:
    """List all running workloads from the ToolHive API"""
    base_url = f"http://{host}:{port}"
    endpoint = "/api/v1beta/workloads"

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{base_url}{endpoint}")
            response.raise_for_status()
            return {
                "success": True,
                "endpoint": endpoint,
                "data": response.json()
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def initialize():
    """
    Initialize the ToolHive client - starts thv serve and returns workload info.

    This function now uses port discovery to automatically find ToolHive,
    making it work in containerized environments and dynamic port scenarios.
    """
    # Register cleanup handler
    atexit.register(stop_thv_serve)

    # Start thv serve
    start_thv_serve()

    # Discover ToolHive using port scanning
    # This will automatically find ToolHive even if it's not on the default port
    try:
        host, port = discover_toolhive()
        print(f"Connected to ToolHive at {host}:{port}\n")
    except ConnectionError as e:
        print(f"Warning: {e}")
        print("Falling back to default connection parameters...\n")
        host, port = DEFAULT_HOST, DEFAULT_PORT

    # List current workloads using discovered connection
    workloads = list_workloads(host=host, port=port)

    print("\n=== Current Workloads ===")
    if workloads.get("success"):
        print(f"Endpoint: {workloads.get('endpoint')}")
        print(f"Data: {workloads.get('data')}")
    else:
        print(f"Error: {workloads.get('error')}")
    print("=" * 25 + "\n")

    # List all tools from MCP servers using discovered connection
    print("=== Available Tools ===")
    try:
        tools_list = asyncio.run(mcp_client.list_tools(host=host, port=port))
        for server_tools in tools_list:
            workload_name = server_tools.get("workload", "unknown")
            status = server_tools.get("status", "unknown")
            tools = server_tools.get("tools", [])
            error = server_tools.get("error")

            print(f"\nWorkload: {workload_name}")
            print(f"  Status: {status}")
            if tools:
                # tools may be a list of dicts ({"name": ..., "description": ...})
                # or a list of strings (back-compat). Normalize to names for display.
                try:
                    names = [
                        (t.get("name") if isinstance(t, dict) else str(t))
                        for t in tools
                    ]
                except Exception:
                    # Fallback: stringify everything
                    names = [str(t) for t in tools]
                print(f"  Tools: {', '.join(names)}")
            if error:
                print(f"  Error: {error}")
    except Exception as e:
        print(f"Error listing tools: {str(e)}")
    print("=" * 25 + "\n")

    return workloads
