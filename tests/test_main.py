import pytest
from unittest.mock import AsyncMock, patch
from main import _list_all_tools_impl, _get_tool_details_impl


@pytest.mark.asyncio
class TestListAllTools:
    async def test_list_all_tools_with_descriptions(self, mocker):
        """Test list_all_tools formats tool descriptions correctly"""
        mock_tools = [
            {
                "workload": "test-server",
                "status": "success",
                "tools": [
                    {"name": "tool1", "description": "A simple tool"},
                    {"name": "tool2", "description": "Another tool"}
                ],
                "error": None
            }
        ]

        mocker.patch("mcp_client.list_tools", return_value=mock_tools)

        result = await _list_all_tools_impl()

        assert "**test-server**" in result
        assert "tool1: A simple tool" in result
        assert "tool2: Another tool" in result

    async def test_list_all_tools_truncates_long_descriptions(self, mocker):
        """Test that long descriptions are truncated to 200 chars"""
        long_description = "a" * 250  # 250 characters

        mock_tools = [
            {
                "workload": "test-server",
                "status": "success",
                "tools": [
                    {"name": "tool1", "description": long_description}
                ],
                "error": None
            }
        ]

        mocker.patch("mcp_client.list_tools", return_value=mock_tools)

        result = await _list_all_tools_impl()

        # Should be truncated to 200 chars + "..."
        assert "tool1: " + "a" * 200 + "..." in result
        assert "a" * 210 not in result  # Full string shouldn't be there

    async def test_list_all_tools_replaces_newlines(self, mocker):
        """Test that newlines in descriptions are replaced with spaces"""
        description_with_newlines = "Line 1\nLine 2\r\nLine 3"

        mock_tools = [
            {
                "workload": "test-server",
                "status": "success",
                "tools": [
                    {"name": "tool1", "description": description_with_newlines}
                ],
                "error": None
            }
        ]

        mocker.patch("mcp_client.list_tools", return_value=mock_tools)

        result = await _list_all_tools_impl()

        # Newlines should be replaced with spaces (note: \r\n becomes two spaces)
        assert "Line 1 Line 2  Line 3" in result
        # Check that the description itself doesn't contain literal \n or \r characters
        description_part = result.split("tool1:")[1].split("\n")[0] if "tool1:" in result else ""
        assert "\n" not in description_part and "\r" not in description_part

    async def test_list_all_tools_handles_empty_description(self, mocker):
        """Test handling of tools with empty descriptions"""
        mock_tools = [
            {
                "workload": "test-server",
                "status": "success",
                "tools": [
                    {"name": "tool1", "description": ""},
                    {"name": "tool2", "description": None}
                ],
                "error": None
            }
        ]

        mocker.patch("mcp_client.list_tools", return_value=mock_tools)

        result = await _list_all_tools_impl()

        # Tools without descriptions should just show the name
        assert "  - tool1" in result
        assert "  - tool2" in result

    async def test_list_all_tools_backwards_compatibility(self, mocker):
        """Test backwards compatibility with tools as list of strings"""
        mock_tools = [
            {
                "workload": "test-server",
                "status": "success",
                "tools": ["tool1", "tool2"],  # Old format: just names
                "error": None
            }
        ]

        mocker.patch("mcp_client.list_tools", return_value=mock_tools)

        result = await _list_all_tools_impl()

        assert "- tool1" in result
        assert "- tool2" in result

    async def test_list_all_tools_no_servers(self, mocker):
        """Test when no MCP servers are found"""
        mocker.patch("mcp_client.list_tools", return_value=[])

        result = await _list_all_tools_impl()

        assert result == "No MCP servers found"

    async def test_list_all_tools_with_error(self, mocker):
        """Test tool listing with server errors"""
        mock_tools = [
            {
                "workload": "test-server",
                "status": "error",
                "tools": [],
                "error": "Connection timeout"
            }
        ]

        mocker.patch("mcp_client.list_tools", return_value=mock_tools)

        result = await _list_all_tools_impl()

        assert "**test-server**" in result
        assert "Connection timeout" in result

    async def test_list_all_tools_hides_orchestrator(self, mocker):
        """Test that orchestrator workloads are hidden from the output"""
        mock_tools = [
            {
                "workload": "fetch",
                "status": "success",
                "tools": [{"name": "fetch", "description": "Fetches URLs"}],
                "error": None
            },
            {
                "workload": "model-context-shell",
                "status": "skipped",
                "tools": [],
                "error": "Skipped: orchestrator workload (self)"
            },
            {
                "workload": "database",
                "status": "success",
                "tools": [{"name": "query", "description": "Queries database"}],
                "error": None
            }
        ]

        mocker.patch("mcp_client.list_tools", return_value=mock_tools)

        result = await _list_all_tools_impl()

        # Should show the real tool servers
        assert "**fetch**" in result
        assert "**database**" in result

        # Should NOT show the orchestrator
        assert "model-context-shell" not in result
        assert "orchestrator" not in result


@pytest.mark.asyncio
class TestGetToolDetails:
    async def test_get_tool_details_success(self, mocker):
        """Test successful tool detail retrieval"""
        mock_details = {
            "name": "test_tool",
            "description": "A detailed description of the test tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                    "param2": {"type": "number"}
                }
            }
        }

        mocker.patch("mcp_client.get_tool_details_from_server", return_value=mock_details)

        result = await _get_tool_details_impl("test-server", "test_tool")

        assert "Tool: test_tool" in result
        assert "A detailed description of the test tool" in result
        assert '"param1"' in result
        assert '"param2"' in result

    async def test_get_tool_details_with_error(self, mocker):
        """Test tool details when error occurs"""
        mock_details = {
            "error": "Tool not found"
        }

        mocker.patch("mcp_client.get_tool_details_from_server", return_value=mock_details)

        result = await _get_tool_details_impl("test-server", "nonexistent")

        assert "Error: Tool not found" in result

    async def test_get_tool_details_formats_schema(self, mocker):
        """Test that input schema is formatted as JSON"""
        mock_details = {
            "name": "test_tool",
            "description": "Test",
            "inputSchema": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"}
                }
            }
        }

        mocker.patch("mcp_client.get_tool_details_from_server", return_value=mock_details)

        result = await _get_tool_details_impl("test-server", "test_tool")

        # Check JSON formatting
        assert "Input Schema:" in result
        assert '"type": "object"' in result
        assert '"required": [' in result
        assert '"url"' in result

    async def test_get_tool_details_no_description(self, mocker):
        """Test tool details with missing description"""
        mock_details = {
            "name": "test_tool",
            "description": None,
            "inputSchema": {"type": "object"}
        }

        mocker.patch("mcp_client.get_tool_details_from_server", return_value=mock_details)

        result = await _get_tool_details_impl("test-server", "test_tool")

        assert "Tool: test_tool" in result
        # Should have fallback text
        assert "Input Schema:" in result
