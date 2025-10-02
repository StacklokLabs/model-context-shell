import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx
import mcp_client


@pytest.mark.asyncio
class TestGetWorkloads:
    async def test_successful_get_workloads(self, mocker):
        """Test successful retrieval of workloads"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "workloads": [
                {"name": "workload1", "status": "running"},
                {"name": "workload2", "status": "running"}
            ]
        }

        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await mcp_client.get_workloads()

        assert len(result) == 2
        assert result[0]["name"] == "workload1"
        assert result[1]["name"] == "workload2"

    async def test_get_workloads_with_custom_host_port(self, mocker):
        """Test get_workloads with custom host and port"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"workloads": []}

        mock_get = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get = mock_get
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        await mcp_client.get_workloads(host="192.168.1.1", port=9000)

        mock_get.assert_called_once_with("http://192.168.1.1:9000/api/v1beta/workloads")

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
            "url": "http://localhost:8080/mcp"
        }

        # Mock the MCP client
        mock_session = MagicMock()
        mock_session.initialize = AsyncMock()

        mock_tool = MagicMock()
        mock_tool.name = "test_tool_1"
        mock_tool2 = MagicMock()
        mock_tool2.name = "test_tool_2"

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
        assert result["tools"] == ["test_tool_1", "test_tool_2"]
        assert result["error"] is None

    async def test_unsupported_transport(self):
        """Test unsupported transport type"""
        workload = {
            "name": "test-workload",
            "status": "running",
            "transport_type": "stdio",
            "url": "http://localhost:8080/mcp"
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
            "url": "http://localhost:8080/mcp"
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
            "url": ""
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
            "url": "http://localhost:8080/mcp"
        }

        mocker.patch("mcp_client.streamablehttp_client", side_effect=Exception("Connection failed"))

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
            {"name": "workload2", "status": "running"}
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
            "mcp_client.get_workloads",
            side_effect=httpx.HTTPError("Connection failed")
        )

        result = await mcp_client.list_tools()

        assert len(result) == 1
        assert result[0]["status"] == "error"
        assert "Failed to get workload list" in result[0]["error"]

    async def test_list_tools_handles_individual_failures(self, mocker):
        """Test that list_tools handles individual workload failures gracefully"""
        mock_workloads = [
            {"name": "workload1", "status": "running"},
            {"name": "workload2", "status": "running"}
        ]
        mocker.patch("mcp_client.get_workloads", return_value=mock_workloads)

        # Mock one success and one failure
        async def mock_list_tools(workload):
            if workload["name"] == "workload1":
                return {
                    "workload": "workload1",
                    "status": "success",
                    "tools": ["tool1"],
                    "error": None
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
