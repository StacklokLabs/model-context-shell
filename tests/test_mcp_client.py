from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import mcp_client


@pytest.mark.asyncio
class TestGetWorkloads:
    async def test_successful_get_workloads(self, mocker):
        """Test successful retrieval of workloads"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "workloads": [
                {"name": "workload1", "status": "running"},
                {"name": "workload2", "status": "running"},
            ]
        }

        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await mcp_client.get_workloads()

        assert len(result) == 2
        assert result[0]["name"] == "workload1"
        assert result[1]["name"] == "workload2"

    async def test_get_workloads_http_error(self, mocker):
        """Test get_workloads when HTTP error occurs"""
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.HTTPError("Connection failed")
        )
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        with pytest.raises(httpx.HTTPError):
            await mcp_client.get_workloads()


@pytest.mark.asyncio
class TestListToolsFromServer:
    async def test_successful_connection(self, mocker):
        """Test successful connection and tool listing"""
        workload = {
            "name": "test-workload",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        # Mock the MCP client
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        mock_tool = MagicMock()
        mock_tool.name = "test_tool_1"
        mock_tool.description = "Description for tool 1"
        mock_tool2 = MagicMock()
        mock_tool2.name = "test_tool_2"
        mock_tool2.description = "Description for tool 2"

        mock_tools_response = MagicMock()
        mock_tools_response.tools = [mock_tool, mock_tool2]
        mock_session.list_tools = AsyncMock(return_value=mock_tools_response)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.list_tools_from_server(workload)

        assert result["workload"] == "test-workload"
        assert result["status"] == "success"
        assert len(result["tools"]) == 2
        assert result["tools"][0] == {
            "name": "test_tool_1",
            "description": "Description for tool 1",
        }
        assert result["tools"][1] == {
            "name": "test_tool_2",
            "description": "Description for tool 2",
        }
        assert result["error"] is None

    async def test_sse_proxy_connection(self, mocker):
        """Test successful connection via SSE proxy"""
        workload = {
            "name": "test-workload",
            "status": "running",
            "transport_type": "stdio",
            "proxy_mode": "sse",
            "url": "http://localhost:8080/sse",
        }

        # Mock the MCP client
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        mock_tool = MagicMock()
        mock_tool.name = "sse_tool"
        mock_tool.description = "SSE tool description"

        mock_tools_response = MagicMock()
        mock_tools_response.tools = [mock_tool]
        mock_session.list_tools = AsyncMock(return_value=mock_tools_response)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=("read", "write"))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.sse_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.list_tools_from_server(workload)

        assert result["workload"] == "test-workload"
        assert result["status"] == "success"
        assert len(result["tools"]) == 1
        assert result["tools"][0] == {
            "name": "sse_tool",
            "description": "SSE tool description",
        }
        assert result["error"] is None

    async def test_unsupported_transport(self):
        """Test unsupported transport type"""
        workload = {
            "name": "test-workload",
            "status": "running",
            "transport_type": "stdio",
            "url": "http://localhost:8080/mcp",
        }

        result = await mcp_client.list_tools_from_server(workload)

        assert result["workload"] == "test-workload"
        assert result["status"] == "unsupported"
        assert result["tools"] == []
        assert "stdio" in result["error"]

    async def test_non_running_workload(self):
        """Test workload that is not running"""
        workload = {
            "name": "test-workload",
            "status": "stopped",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        result = await mcp_client.list_tools_from_server(workload)

        assert result["workload"] == "test-workload"
        assert result["status"] == "skipped"
        assert result["tools"] == []
        assert "stopped" in result["error"]

    async def test_missing_url(self):
        """Test workload with missing URL"""
        workload = {
            "name": "test-workload",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "",
        }

        result = await mcp_client.list_tools_from_server(workload)

        assert result["workload"] == "test-workload"
        assert result["status"] == "error"
        assert result["tools"] == []
        assert "No URL" in result["error"]

    async def test_connection_error(self, mocker):
        """Test connection error handling"""
        workload = {
            "name": "test-workload",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch(
            "mcp_client.streamablehttp_client",
            side_effect=Exception("Connection failed"),
        )

        result = await mcp_client.list_tools_from_server(workload)

        assert result["workload"] == "test-workload"
        assert result["status"] == "error"
        assert result["tools"] == []
        assert "Connection failed" in result["error"]

    async def test_handles_missing_name(self):
        """Test handling of workload without name"""
        workload = {"status": "stopped"}

        result = await mcp_client.list_tools_from_server(workload)

        assert result["workload"] == "unknown"
        assert result["status"] == "skipped"


@pytest.mark.asyncio
class TestListTools:
    async def test_list_tools_with_multiple_workloads(self, mocker):
        """Test list_tools with multiple workloads"""
        mock_workloads = [
            {"name": "workload1", "status": "running"},
            {"name": "workload2", "status": "running"},
        ]
        mocker.patch("mcp_client.get_workloads", return_value=mock_workloads)

        result = await mcp_client.list_tools()

        assert len(result) == 2
        assert result[0]["workload"] == "workload1"
        assert result[1]["workload"] == "workload2"

    async def test_list_tools_with_empty_workloads(self, mocker):
        """Test list_tools when no workloads exist"""
        mocker.patch("mcp_client.get_workloads", return_value=[])

        result = await mcp_client.list_tools()

        assert result == []

    async def test_list_tools_with_api_error(self, mocker):
        """Test list_tools when API call fails"""
        mocker.patch(
            "mcp_client.get_workloads", side_effect=httpx.HTTPError("Connection failed")
        )

        result = await mcp_client.list_tools()

        assert len(result) == 1
        assert result[0]["status"] == "error"
        assert "Failed to get workload list" in result[0]["error"]

    async def test_list_tools_handles_individual_failures(self, mocker):
        """Test that list_tools handles individual workload failures gracefully"""
        mock_workloads = [
            {"name": "workload1", "status": "running"},
            {"name": "workload2", "status": "running"},
        ]
        mocker.patch("mcp_client.get_workloads", return_value=mock_workloads)

        # Mock one success and one failure
        async def mock_list_tools(workload):
            if workload["name"] == "workload1":
                return {
                    "workload": "workload1",
                    "status": "success",
                    "tools": ["tool1"],
                    "error": None,
                }
            raise Exception("Connection timeout")

        mocker.patch("mcp_client.list_tools_from_server", side_effect=mock_list_tools)

        result = await mcp_client.list_tools()

        assert len(result) == 2
        assert result[0]["status"] == "success"
        assert result[1]["status"] == "error"
        assert "Connection timeout" in result[1]["error"]

    async def test_list_tools_with_custom_host_port(self, mocker):
        """Test list_tools with custom host and port"""
        mock_get_workloads = mocker.patch("mcp_client.get_workloads", return_value=[])

        await mcp_client.list_tools(host="localhost", port=9000)

        mock_get_workloads.assert_called_once_with("localhost", 9000)

    async def test_list_tools_handles_missing_description(self, mocker):
        """Test that tools with None description are handled correctly"""
        workload = {
            "name": "test-workload",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        # Mock the MCP client
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = None

        mock_tools_response = MagicMock()
        mock_tools_response.tools = [mock_tool]
        mock_session.list_tools = AsyncMock(return_value=mock_tools_response)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.list_tools_from_server(workload)

        assert result["tools"][0] == {"name": "test_tool", "description": ""}


@pytest.mark.asyncio
class TestGetToolDetails:
    async def test_get_tool_details_success(self, mocker):
        """Test successful retrieval of tool details"""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])

        # Mock discover_toolhive to return host and port
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        # Mock the MCP client
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool for testing"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"param1": {"type": "string"}, "param2": {"type": "number"}},
            "required": ["param1"],
        }

        mock_tools_response = MagicMock()
        mock_tools_response.tools = [mock_tool]
        mock_session.list_tools = AsyncMock(return_value=mock_tools_response)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.get_tool_details_from_server(
            "test-server", "test_tool"
        )

        assert result["name"] == "test_tool"
        assert result["description"] == "A test tool for testing"
        assert result["inputSchema"]["type"] == "object"
        assert "param1" in result["inputSchema"]["properties"]

    async def test_get_tool_details_workload_not_found(self, mocker):
        """Test get_tool_details when workload doesn't exist"""
        mocker.patch("mcp_client.get_workloads", return_value=[])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        result = await mcp_client.get_tool_details_from_server(
            "nonexistent", "test_tool"
        )

        assert "error" in result
        assert "not found" in result["error"]

    async def test_get_tool_details_tool_not_found(self, mocker):
        """Test get_tool_details when tool doesn't exist in workload"""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        # Mock the MCP client with a different tool
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        mock_tool = MagicMock()
        mock_tool.name = "other_tool"
        mock_tool.description = "Another tool"
        mock_tool.inputSchema = {}

        mock_tools_response = MagicMock()
        mock_tools_response.tools = [mock_tool]
        mock_session.list_tools = AsyncMock(return_value=mock_tools_response)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.get_tool_details_from_server(
            "test-server", "nonexistent_tool"
        )

        assert "error" in result
        assert "not found" in result["error"]

    async def test_get_tool_details_sse_transport(self, mocker):
        """Test get_tool_details with SSE transport"""
        workload = {
            "name": "test-server",
            "status": "running",
            "proxy_mode": "sse",
            "url": "http://localhost:8080/sse",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        # Mock the MCP client
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        mock_tool = MagicMock()
        mock_tool.name = "sse_tool"
        mock_tool.description = "SSE tool"
        mock_tool.inputSchema = {"type": "object"}

        mock_tools_response = MagicMock()
        mock_tools_response.tools = [mock_tool]
        mock_session.list_tools = AsyncMock(return_value=mock_tools_response)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=("read", "write"))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.sse_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.get_tool_details_from_server(
            "test-server", "sse_tool"
        )

        assert result["name"] == "sse_tool"
        assert result["description"] == "SSE tool"

    async def test_get_tool_details_connection_error(self, mocker):
        """Test get_tool_details handles connection errors"""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )
        mocker.patch(
            "mcp_client.streamablehttp_client",
            side_effect=Exception("Connection failed"),
        )

        result = await mcp_client.get_tool_details_from_server(
            "test-server", "test_tool"
        )

        assert "error" in result
        assert "Connection failed" in result["error"]


@pytest.mark.asyncio
class TestCallTool:
    """Test the call_tool function"""

    async def test_call_tool_success_streamable_http(self, mocker):
        """Test successful tool call via streamable-http"""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        # Mock the MCP client
        mock_result = MagicMock()
        mock_result.content = [MagicMock(text="tool result")]

        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_http.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_http)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.call_tool(
            "test-server", "test_tool", {"param": "value"}
        )

        assert result == mock_result
        mock_session.call_tool.assert_called_once_with(
            "test_tool", arguments={"param": "value"}
        )

    async def test_call_tool_success_sse(self, mocker):
        """Test successful tool call via SSE"""
        workload = {
            "name": "test-server",
            "status": "running",
            "proxy_mode": "sse",
            "url": "http://localhost:8080/sse",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        mock_result = MagicMock()

        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=("read", "write"))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.sse_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.call_tool(
            "test-server", "test_tool", {"param": "value"}
        )

        assert result == mock_result

    async def test_call_tool_workload_not_found(self, mocker):
        """Test call_tool when workload doesn't exist"""
        mocker.patch("mcp_client.get_workloads", return_value=[])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        with pytest.raises(ValueError, match="not found"):
            await mcp_client.call_tool("nonexistent", "test_tool", {})

    async def test_call_tool_workload_not_running(self, mocker):
        """Test call_tool when workload is not running"""
        workload = {
            "name": "test-server",
            "status": "stopped",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        with pytest.raises(RuntimeError, match="not running"):
            await mcp_client.call_tool("test-server", "test_tool", {})

    async def test_call_tool_no_url(self, mocker):
        """Test call_tool when workload has no URL"""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        with pytest.raises(ValueError, match="No URL"):
            await mcp_client.call_tool("test-server", "test_tool", {})

    async def test_call_tool_unsupported_transport(self, mocker):
        """Test call_tool with unsupported transport"""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "stdio",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        with pytest.raises(ValueError, match="not supported"):
            await mcp_client.call_tool("test-server", "test_tool", {})

    async def test_call_tool_discovery_fallback(self, mocker):
        """Test call_tool falls back to defaults when discovery fails"""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mock_get_workloads = mocker.patch(
            "mcp_client.get_workloads", return_value=[workload]
        )
        mocker.patch(
            "toolhive_client.discover_toolhive",
            side_effect=Exception("Discovery failed"),
        )

        mock_result = MagicMock()
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_http.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_http)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        # Should not raise, should fall back to defaults
        result = await mcp_client.call_tool("test-server", "test_tool", {})

        assert result == mock_result
        # Should have been called with default host/port
        mock_get_workloads.assert_called_once_with("127.0.0.1", 8080)


@pytest.mark.asyncio
class TestGetWorkloadsUrlRewriting:
    """Test localhost URL rewriting for container networking"""

    async def test_rewrites_localhost_urls(self, mocker):
        """Test that localhost URLs are rewritten to use the actual host"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "workloads": [
                {
                    "name": "workload1",
                    "url": "http://localhost:9000/mcp",
                },
                {
                    "name": "workload2",
                    "url": "http://127.0.0.1:9001/sse",
                },
            ]
        }

        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        # Call with a different host (simulating container environment)
        result = await mcp_client.get_workloads(host="192.168.1.100", port=8080)

        # URLs should be rewritten
        assert result[0]["url"] == "http://192.168.1.100:9000/mcp"
        assert result[1]["url"] == "http://192.168.1.100:9001/sse"

    async def test_preserves_non_localhost_urls(self, mocker):
        """Test that non-localhost URLs are not rewritten"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "workloads": [
                {
                    "name": "workload1",
                    "url": "http://some-service:9000/mcp",
                },
            ]
        }

        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await mcp_client.get_workloads(host="192.168.1.100", port=8080)

        # URL should not be rewritten
        assert result[0]["url"] == "http://some-service:9000/mcp"


@pytest.mark.asyncio
class TestBatchCallTool:
    """Test batch tool calling for connection reuse in for_each scenarios."""

    async def test_batch_call_tool_reuses_connection(self, mocker):
        """Test that batch_call_tool opens only ONE connection for multiple calls.

        This is critical for for_each pipelines: with 38 Pokemon URLs,
        opening a new connection per call causes 10+ minute hangs.
        The fix is to reuse a single MCP session for all calls.
        """
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        # Track how many times we open a connection
        connection_open_count = 0

        mock_result = MagicMock()
        mock_result.content = [MagicMock(text="result")]

        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        def tracking_streamablehttp_client(url):
            nonlocal connection_open_count
            connection_open_count += 1
            mock_http = MagicMock()
            mock_http.__aenter__ = AsyncMock(
                return_value=("read", "write", lambda: None)
            )
            mock_http.__aexit__ = AsyncMock()
            return mock_http

        mocker.patch(
            "mcp_client.streamablehttp_client",
            side_effect=tracking_streamablehttp_client,
        )
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        # Make 10 tool calls - simulating for_each with 10 items
        call_args_list = [{"id": i} for i in range(10)]

        # Use batch_call_tool - should only open ONE connection
        results = await mcp_client.batch_call_tool(
            "test-server", "fetch", call_args_list
        )

        # Should only open ONE connection for all 10 calls
        assert connection_open_count == 1, (
            f"Expected 1 connection for batch call, got {connection_open_count}"
        )

        # Should return 10 results
        assert len(results) == 10

        # Session's call_tool should have been called 10 times
        assert mock_session.call_tool.call_count == 10

    async def test_batch_call_tool_empty_list(self, mocker):
        """Test that batch_call_tool handles empty list without opening connections."""
        connection_open_count = 0

        def tracking_streamablehttp_client(url):
            nonlocal connection_open_count
            connection_open_count += 1
            return MagicMock()

        mocker.patch(
            "mcp_client.streamablehttp_client",
            side_effect=tracking_streamablehttp_client,
        )

        results = await mcp_client.batch_call_tool("test-server", "fetch", [])

        assert results == []
        assert connection_open_count == 0  # No connections opened for empty list

    async def test_batch_call_tool_sse_transport(self, mocker):
        """Test batch_call_tool works with SSE transport."""
        workload = {
            "name": "test-server",
            "status": "running",
            "proxy_mode": "sse",
            "url": "http://localhost:8080/sse",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        connection_open_count = 0

        mock_result = MagicMock()
        mock_result.content = [MagicMock(text="sse_result")]

        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        def tracking_sse_client(url):
            nonlocal connection_open_count
            connection_open_count += 1
            mock_sse = MagicMock()
            mock_sse.__aenter__ = AsyncMock(return_value=("read", "write"))
            mock_sse.__aexit__ = AsyncMock()
            return mock_sse

        mocker.patch("mcp_client.sse_client", side_effect=tracking_sse_client)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        call_args_list = [{"id": i} for i in range(5)]
        results = await mcp_client.batch_call_tool(
            "test-server", "fetch", call_args_list
        )

        assert connection_open_count == 1
        assert len(results) == 5

    async def test_batch_call_tool_workload_not_found(self, mocker):
        """Test batch_call_tool raises error for non-existent workload."""
        mocker.patch("mcp_client.get_workloads", return_value=[])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        with pytest.raises(ValueError, match="not found"):
            await mcp_client.batch_call_tool("nonexistent", "fetch", [{"id": 1}])


@pytest.mark.asyncio
class TestBatchCallToolPartialFailure:
    """Test error reporting when some calls in a batch fail."""

    async def test_batch_call_tool_reports_failure_index(self, mocker):
        """Test that batch_call_tool reports which item failed."""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        call_count = 0

        async def failing_on_third_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("API rate limit exceeded")
            mock_result = MagicMock()
            mock_result.content = [MagicMock(text=f"result_{call_count}")]
            return mock_result

        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = MagicMock(side_effect=failing_on_third_call)

        mock_client_session_instance = MagicMock()
        mock_client_session_instance.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session_instance.__aexit__ = AsyncMock(return_value=None)

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_http.__aexit__ = AsyncMock(return_value=None)

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_http)
        mocker.patch(
            "mcp_client.ClientSession", return_value=mock_client_session_instance
        )

        call_args_list = [{"id": i} for i in range(5)]

        with pytest.raises(RuntimeError) as exc_info:
            await mcp_client.batch_call_tool("test-server", "fetch", call_args_list)

        error_msg = str(exc_info.value)

        # Should report which item failed (item 3 of 5)
        assert "item 3" in error_msg.lower() or "3 of 5" in error_msg, (
            f"Error should mention which item failed (item 3). Got: {error_msg}"
        )

        # Should report how many completed successfully
        assert (
            "2 successful" in error_msg.lower() or "2 completed" in error_msg.lower()
        ), f"Error should mention 2 items completed successfully. Got: {error_msg}"

        # Should report how many are still pending
        assert "2 pending" in error_msg.lower(), (
            f"Error should mention 2 items still pending. Got: {error_msg}"
        )

    async def test_batch_call_tool_includes_partial_results(self, mocker):
        """Test that batch_call_tool includes partial results in error."""
        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        call_count = 0

        async def failing_on_third_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("Connection timeout")
            mock_result = MagicMock()
            mock_result.content = [MagicMock(text=f"result_{call_count}")]
            return mock_result

        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = MagicMock(side_effect=failing_on_third_call)

        mock_client_session_instance = MagicMock()
        mock_client_session_instance.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session_instance.__aexit__ = AsyncMock(return_value=None)

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_http.__aexit__ = AsyncMock(return_value=None)

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_http)
        mocker.patch(
            "mcp_client.ClientSession", return_value=mock_client_session_instance
        )

        call_args_list = [{"url": f"http://example.com/{i}"} for i in range(5)]

        with pytest.raises(RuntimeError) as exc_info:
            await mcp_client.batch_call_tool("test-server", "fetch", call_args_list)

        error_msg = str(exc_info.value)

        # Should include partial results that succeeded
        assert "result_1" in error_msg and "result_2" in error_msg, (
            f"Error should include partial results (result_1, result_2). Got: {error_msg}"
        )


@pytest.mark.asyncio
class TestToolCallTimeout:
    """Test timeout handling for tool calls."""

    async def test_call_tool_times_out(self, mocker):
        """Test that call_tool times out after the specified timeout.

        Without timeouts, a hanging tool call can block forever.
        This test verifies that tool calls respect a timeout.
        """
        import asyncio

        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        # Create a session that hangs forever on call_tool
        async def hanging_call_tool(*args, **kwargs):
            await asyncio.sleep(60)  # Hang for 60 seconds

        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = MagicMock(side_effect=hanging_call_tool)

        # ClientSession is used as a context manager: `async with ClientSession(...) as session:`
        # So ClientSession() returns an object, and that object's __aenter__ returns the session
        mock_client_session_instance = MagicMock()
        mock_client_session_instance.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session_instance.__aexit__ = AsyncMock(return_value=None)

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_http.__aexit__ = AsyncMock(return_value=None)

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_http)
        mocker.patch(
            "mcp_client.ClientSession", return_value=mock_client_session_instance
        )

        # Verify DEFAULT_TOOL_TIMEOUT constant exists
        assert hasattr(mcp_client, "DEFAULT_TOOL_TIMEOUT"), (
            "DEFAULT_TOOL_TIMEOUT constant not defined in mcp_client"
        )

        # Use a short timeout for testing (0.5 seconds)
        test_timeout = 0.5

        import time

        start = time.time()

        with pytest.raises(asyncio.TimeoutError):
            await mcp_client.call_tool(
                "test-server", "slow_tool", {"param": "value"}, timeout=test_timeout
            )

        elapsed = time.time() - start

        # Should timeout within reasonable bounds
        assert elapsed < test_timeout + 0.5, (
            f"Tool call took {elapsed}s, expected timeout around {test_timeout}s"
        )
        assert elapsed >= test_timeout * 0.8, (
            f"Tool call returned too quickly ({elapsed}s), timeout may not be working"
        )

    async def test_batch_call_tool_times_out(self, mocker):
        """Test that batch_call_tool also respects timeouts."""
        import asyncio

        workload = {
            "name": "test-server",
            "status": "running",
            "transport_type": "streamable-http",
            "url": "http://localhost:8080/mcp",
        }

        mocker.patch("mcp_client.get_workloads", return_value=[workload])
        mocker.patch(
            "toolhive_client.discover_toolhive", return_value=("localhost", 8080)
        )

        # Create a session that hangs on call_tool
        async def hanging_call_tool(*args, **kwargs):
            await asyncio.sleep(60)

        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = MagicMock(side_effect=hanging_call_tool)

        mock_client_session_instance = MagicMock()
        mock_client_session_instance.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session_instance.__aexit__ = AsyncMock(return_value=None)

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=("read", "write", lambda: None))
        mock_http.__aexit__ = AsyncMock(return_value=None)

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_http)
        mocker.patch(
            "mcp_client.ClientSession", return_value=mock_client_session_instance
        )

        # Use a short timeout for testing (0.5 seconds)
        test_timeout = 0.5

        import time

        start = time.time()

        # batch_call_tool wraps timeout errors in RuntimeError with progress info
        with pytest.raises(RuntimeError) as exc_info:
            await mcp_client.batch_call_tool(
                "test-server", "slow_tool", [{"id": 1}, {"id": 2}], timeout=test_timeout
            )

        elapsed = time.time() - start

        # Should timeout within reasonable bounds
        assert elapsed < test_timeout + 0.5, (
            f"Batch call took {elapsed}s, expected timeout around {test_timeout}s"
        )
        assert elapsed >= test_timeout * 0.8, (
            f"Batch call returned too quickly ({elapsed}s), timeout may not be working"
        )

        # The error should be wrapped with progress info and mention it's a timeout
        error_msg = str(exc_info.value)
        assert "item 1 of 2" in error_msg.lower(), (
            f"Error should indicate which item failed. Got: {error_msg}"
        )


@pytest.mark.asyncio
class TestSelfFiltering:
    """Test that mcp-shell filters itself out from tool listings"""

    async def test_filters_orchestrator_workload_sse(self, mocker):
        """Test that workloads with all orchestrator tools are filtered (SSE)"""
        # Mock workload that looks like mcp-shell itself
        mock_workload = {
            "name": "model-context-shell",
            "status": "running",
            "url": "http://localhost:9000/sse",
            "proxy_mode": "sse",
            "transport_type": "sse",
        }

        # Mock the SSE client session to return our orchestrator tools
        mock_session = AsyncMock()
        mock_tools_response = MagicMock()

        # Create proper mock tools with name and description attributes
        tool1 = MagicMock()
        tool1.name = "list_available_shell_commands"
        tool1.description = ""

        tool2 = MagicMock()
        tool2.name = "execute_pipeline"
        tool2.description = ""

        tool3 = MagicMock()
        tool3.name = "list_all_tools"
        tool3.description = ""

        tool4 = MagicMock()
        tool4.name = "get_tool_details"
        tool4.description = ""

        mock_tools_response.tools = [tool1, tool2, tool3, tool4]
        mock_session.list_tools.return_value = mock_tools_response
        mock_session.initialize = AsyncMock()

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=(None, None))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.sse_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.list_tools_from_server(mock_workload)

        assert result["status"] == "skipped"
        assert result["tools"] == []
        assert "orchestrator" in result["error"]

    async def test_filters_orchestrator_workload_http(self, mocker):
        """Test that workloads with all orchestrator tools are filtered (HTTP)"""
        mock_workload = {
            "name": "shell-orchestrator",
            "status": "running",
            "url": "http://localhost:9000/mcp",
            "proxy_mode": "streamable-http",
            "transport_type": "streamable-http",
        }

        mock_session = AsyncMock()
        mock_tools_response = MagicMock()

        # Create proper mock tools with name and description attributes
        tool1 = MagicMock()
        tool1.name = "list_available_shell_commands"
        tool1.description = ""

        tool2 = MagicMock()
        tool2.name = "execute_pipeline"
        tool2.description = ""

        tool3 = MagicMock()
        tool3.name = "list_all_tools"
        tool3.description = ""

        tool4 = MagicMock()
        tool4.name = "get_tool_details"
        tool4.description = ""

        mock_tools_response.tools = [tool1, tool2, tool3, tool4]
        mock_session.list_tools.return_value = mock_tools_response
        mock_session.initialize = AsyncMock()

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=(None, None, None))
        mock_http.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.streamablehttp_client", return_value=mock_http)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.list_tools_from_server(mock_workload)

        assert result["status"] == "skipped"
        assert result["tools"] == []
        assert "orchestrator" in result["error"]

    async def test_does_not_filter_partial_match(self, mocker):
        """Test that workloads with only some orchestrator tools are not filtered"""
        mock_workload = {
            "name": "partial-server",
            "status": "running",
            "url": "http://localhost:9000/sse",
            "proxy_mode": "sse",
            "transport_type": "sse",
        }

        # Only has 2 of the 4 orchestrator tools
        mock_session = AsyncMock()
        mock_tools_response = MagicMock()

        # Create proper mock tools
        tool1 = MagicMock()
        tool1.name = "list_all_tools"
        tool1.description = "Lists things"

        tool2 = MagicMock()
        tool2.name = "some_other_tool"
        tool2.description = "Does something"

        mock_tools_response.tools = [tool1, tool2]
        mock_session.list_tools.return_value = mock_tools_response
        mock_session.initialize = AsyncMock()

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock()

        mock_sse = MagicMock()
        mock_sse.__aenter__ = AsyncMock(return_value=(None, None))
        mock_sse.__aexit__ = AsyncMock()

        mocker.patch("mcp_client.sse_client", return_value=mock_sse)
        mocker.patch("mcp_client.ClientSession", return_value=mock_client_session)

        result = await mcp_client.list_tools_from_server(mock_workload)

        # Should NOT be filtered
        assert result["status"] == "success"
        assert len(result["tools"]) == 2
        assert result["tools"][0]["name"] == "list_all_tools"
