import subprocess
import atexit
import time
import httpx

# Global variable to hold the thv serve process
thv_process = None

# Default API configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


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
    """Initialize the ToolHive client - starts thv serve and returns workload info"""
    # Register cleanup handler
    atexit.register(stop_thv_serve)

    # Start thv serve
    start_thv_serve()

    # List current workloads
    workloads = list_workloads()

    print("\n=== Current Workloads ===")
    if workloads.get("success"):
        print(f"Endpoint: {workloads.get('endpoint')}")
        print(f"Data: {workloads.get('data')}")
    else:
        print(f"Error: {workloads.get('error')}")
    print("=" * 25 + "\n")

    return workloads
