import pytest
from unittest.mock import MagicMock, patch
import httpx
import toolhive_client


class TestStartThvServe:
    def test_starts_subprocess(self, mocker):
        """Test that start_thv_serve starts a subprocess"""
        mock_popen = mocker.patch("subprocess.Popen")
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        mocker.patch("time.sleep")  # Skip sleep

        toolhive_client.start_thv_serve()

        mock_popen.assert_called_once_with(
            ["thv", "serve"],
            stdout=mocker.ANY,
            stderr=mocker.ANY,
        )
        assert toolhive_client.thv_process == mock_process


class TestStopThvServe:
    def test_stops_running_process(self, mocker):
        """Test that stop_thv_serve terminates the process"""
        mock_process = MagicMock()
        toolhive_client.thv_process = mock_process

        toolhive_client.stop_thv_serve()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once_with(timeout=5)

    def test_kills_process_on_timeout(self, mocker):
        """Test that stop_thv_serve kills process if terminate times out"""
        mock_process = MagicMock()
        mock_process.wait.side_effect = toolhive_client.subprocess.TimeoutExpired("cmd", 5)
        toolhive_client.thv_process = mock_process

        toolhive_client.stop_thv_serve()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()

    def test_does_nothing_if_no_process(self):
        """Test that stop_thv_serve handles None gracefully"""
        toolhive_client.thv_process = None

        # Should not raise an exception
        toolhive_client.stop_thv_serve()


class TestListWorkloads:
    def test_successful_api_call(self, mocker):
        """Test successful API call to list workloads"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"name": "test-workload"}]

        mock_client = MagicMock()
        mock_client.__enter__.return_value.get.return_value = mock_response
        mocker.patch("httpx.Client", return_value=mock_client)

        result = toolhive_client.list_workloads()

        assert result["success"] is True
        assert result["endpoint"] == "/api/v1beta/workloads"
        assert result["data"] == [{"name": "test-workload"}]

    def test_api_call_failure(self, mocker):
        """Test API call failure handling"""
        mock_client = MagicMock()
        mock_client.__enter__.return_value.get.side_effect = httpx.HTTPError("Connection failed")
        mocker.patch("httpx.Client", return_value=mock_client)

        result = toolhive_client.list_workloads()

        assert result["success"] is False
        assert "Connection failed" in result["error"]

    def test_custom_host_port(self, mocker):
        """Test list_workloads with custom host and port"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        mock_get = MagicMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.__enter__.return_value.get = mock_get
        mocker.patch("httpx.Client", return_value=mock_client)

        toolhive_client.list_workloads(host="192.168.1.1", port=9000)

        mock_get.assert_called_once_with("http://192.168.1.1:9000/api/v1beta/workloads")


class TestInitialize:
    def test_initialization_flow(self, mocker):
        """Test complete initialization flow"""
        mock_atexit = mocker.patch("atexit.register")
        mock_start = mocker.patch("toolhive_client.start_thv_serve")
        mock_list = mocker.patch("toolhive_client.list_workloads")
        mock_list.return_value = {
            "success": True,
            "endpoint": "/api/v1beta/workloads",
            "data": []
        }
        # Mock mcp_client.list_tools to prevent coroutine creation
        mocker.patch("mcp_client.list_tools", return_value=[])
        mocker.patch("asyncio.run", return_value=[])

        result = toolhive_client.initialize()

        mock_atexit.assert_any_call(toolhive_client.stop_thv_serve)
        mock_start.assert_called_once()
        mock_list.assert_called_once()
        assert result["success"] is True

    def test_initialization_with_error(self, mocker):
        """Test initialization when workload listing fails"""
        mocker.patch("atexit.register")
        mocker.patch("toolhive_client.start_thv_serve")
        mock_list = mocker.patch("toolhive_client.list_workloads")
        mock_list.return_value = {
            "success": False,
            "error": "Connection refused"
        }
        # Mock mcp_client.list_tools to prevent coroutine creation
        mocker.patch("mcp_client.list_tools", return_value=[])
        mocker.patch("asyncio.run", return_value=[])

        result = toolhive_client.initialize()

        assert result["success"] is False
        assert result["error"] == "Connection refused"
