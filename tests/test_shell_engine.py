import pytest
from unittest.mock import AsyncMock, MagicMock
from shell_engine import ShellEngine
import json


class MockToolResult:
    """Mock object that mimics MCP tool result structure."""
    def __init__(self, text: str):
        self.content = [MockContent(text)]


class MockContent:
    """Mock object for result content."""
    def __init__(self, text: str):
        self.text = text


@pytest.mark.asyncio
class TestShellEngineInitialization:
    """Test ShellEngine initialization and configuration."""

    async def test_initialization_with_tool_caller(self):
        """Test that ShellEngine initializes with a tool caller."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        assert engine.tool_caller == mock_caller
        assert len(engine.allowed_commands) > 0

    async def test_initialization_with_custom_commands(self):
        """Test initialization with custom allowed commands."""
        mock_caller = AsyncMock()
        custom_commands = ["echo", "cat"]

        engine = ShellEngine(tool_caller=mock_caller, allowed_commands=custom_commands)

        assert engine.allowed_commands == custom_commands

    async def test_list_available_commands(self):
        """Test that list_available_commands returns a copy."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        commands = engine.list_available_commands()

        assert "jq" in commands
        assert "grep" in commands
        # Verify it's a copy, not the original
        commands.append("dangerous_command")
        assert "dangerous_command" not in engine.allowed_commands


@pytest.mark.asyncio
class TestCommandValidation:
    """Test command validation logic."""

    async def test_validate_allowed_command(self):
        """Test that allowed commands pass validation."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Should not raise
        engine.validate_command("jq")
        engine.validate_command("grep")
        engine.validate_command("echo")

    async def test_validate_disallowed_command(self):
        """Test that disallowed commands fail validation."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        with pytest.raises(ValueError, match="not allowed"):
            engine.validate_command("rm")

        with pytest.raises(ValueError, match="not allowed"):
            engine.validate_command("bash")

    async def test_validate_empty_command(self):
        """Test that empty command fails validation."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        with pytest.raises(ValueError, match="Empty command"):
            engine.validate_command("")


@pytest.mark.asyncio
class TestShellStage:
    """Test shell_stage execution."""

    async def test_shell_stage_simple_echo(self):
        """Test simple echo command."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        upstream = iter([""])
        result = list(engine.shell_stage("echo", ["hello world"], upstream))

        output = "".join(result).strip()
        assert output == "hello world"

    async def test_shell_stage_with_input(self):
        """Test shell command with stdin input."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        upstream = iter(["apple\nbanana\ncherry\n"])
        result = list(engine.shell_stage("grep", ["a"], upstream))

        output = "".join(result)
        assert "apple" in output
        assert "banana" in output
        assert "cherry" not in output

    async def test_shell_stage_with_jq(self):
        """Test jq command for JSON processing."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        json_input = json.dumps({"name": "test", "value": 123})
        upstream = iter([json_input])
        result = list(engine.shell_stage("jq", [".name"], upstream))

        output = "".join(result).strip()
        assert '"test"' in output

    async def test_shell_stage_for_each_mode(self):
        """Test shell command with for_each=True."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Each line processed separately - using grep to filter
        upstream = iter(["apple\nbanana\napricot\n"])
        result = list(engine.shell_stage("grep", ["^a"], upstream, for_each=True))

        output = "".join(result)
        # Only lines starting with 'a' should pass through
        assert "apple" in output
        assert "apricot" in output
        assert "banana" not in output

    async def test_shell_stage_empty_input(self):
        """Test shell command with empty input."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        upstream = iter([""])
        result = list(engine.shell_stage("cat", [], upstream))

        output = "".join(result)
        assert output == ""


@pytest.mark.asyncio
class TestToolStage:
    """Test tool_stage execution with mocked tool caller."""

    async def test_tool_stage_simple_call(self):
        """Test simple tool call."""
        mock_caller = AsyncMock(return_value=MockToolResult("tool output"))
        engine = ShellEngine(tool_caller=mock_caller)

        upstream = iter([""])
        result = await engine.tool_stage("test_server", "test_tool", {"param": "value"}, upstream)

        assert result == "tool output"
        mock_caller.assert_called_once_with("test_server", "test_tool", {"param": "value"})

    async def test_tool_stage_with_json_input(self):
        """Test tool call with JSON input that gets merged with args."""
        mock_caller = AsyncMock(return_value=MockToolResult("merged output"))
        engine = ShellEngine(tool_caller=mock_caller)

        json_input = json.dumps({"upstream_param": "upstream_value"})
        upstream = iter([json_input])

        result = await engine.tool_stage(
            "test_server", "test_tool",
            {"explicit_param": "explicit_value"},
            upstream
        )

        # Args should be merged (explicit takes precedence)
        mock_caller.assert_called_once()
        call_args = mock_caller.call_args[0][2]
        assert call_args["upstream_param"] == "upstream_value"
        assert call_args["explicit_param"] == "explicit_value"

    async def test_tool_stage_for_each_with_jsonl(self):
        """Test tool call with for_each=True and JSONL input."""
        mock_caller = AsyncMock(return_value=MockToolResult("result"))
        engine = ShellEngine(tool_caller=mock_caller)

        # JSONL input: one JSON object per line
        jsonl_input = '{"url": "http://example.com/1"}\n{"url": "http://example.com/2"}\n'
        upstream = iter([jsonl_input])

        result = await engine.tool_stage("test_server", "fetch", {}, upstream, for_each=True)

        # Should be called twice (once per line)
        assert mock_caller.call_count == 2
        assert "result" in result

    async def test_tool_stage_for_each_invalid_json(self):
        """Test tool call with for_each and invalid JSON raises error."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        invalid_input = 'not valid json\n'
        upstream = iter([invalid_input])

        with pytest.raises(ValueError, match="Invalid JSON"):
            await engine.tool_stage("test_server", "test_tool", {}, upstream, for_each=True)

    async def test_tool_stage_for_each_non_dict_json(self):
        """Test tool call with for_each and non-dict JSON raises error."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # JSON array instead of object
        array_input = '["item1", "item2"]\n'
        upstream = iter([array_input])

        with pytest.raises(ValueError, match="Expected JSON object"):
            await engine.tool_stage("test_server", "test_tool", {}, upstream, for_each=True)

    async def test_tool_stage_tool_error_handling(self):
        """Test tool call error handling in for_each mode."""
        mock_caller = AsyncMock(side_effect=Exception("Tool failed"))
        engine = ShellEngine(tool_caller=mock_caller)

        # Use JSONL input for for_each mode
        upstream = iter(['{"param": "value"}\n'])

        with pytest.raises(RuntimeError, match="Tool failed"):
            await engine.tool_stage("test_server", "test_tool", {}, upstream, for_each=True)

    async def test_tool_stage_result_with_no_content_attribute(self):
        """Test tool result that doesn't have content attribute."""
        mock_caller = AsyncMock(return_value="plain string result")
        engine = ShellEngine(tool_caller=mock_caller)

        upstream = iter([""])
        result = await engine.tool_stage("test_server", "test_tool", {}, upstream)

        assert result == "plain string result"


@pytest.mark.asyncio
class TestExecutePipeline:
    """Test execute_pipeline with various pipeline configurations."""

    async def test_execute_pipeline_single_command(self):
        """Test pipeline with single shell command."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "command", "command": "echo", "args": ["test output"]}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "test output" in result

    async def test_execute_pipeline_multiple_commands(self):
        """Test pipeline with multiple shell commands."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "command", "command": "echo", "args": ["apple\nbanana\ncherry"]},
            {"type": "command", "command": "grep", "args": ["a"]}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "apple" in result
        assert "banana" in result
        assert "cherry" not in result

    async def test_execute_pipeline_with_tool(self):
        """Test pipeline with tool call."""
        mock_caller = AsyncMock(return_value=MockToolResult("tool result"))
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "tool", "name": "test_tool", "server": "test_server", "args": {"key": "value"}}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "tool result" in result
        mock_caller.assert_called_once()

    async def test_execute_pipeline_mixed_stages(self):
        """Test pipeline with mixed command and tool stages."""
        mock_caller = AsyncMock(return_value=MockToolResult('{"data": "test"}'))
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "tool", "name": "fetch", "server": "http", "args": {"url": "http://example.com"}},
            {"type": "command", "command": "jq", "args": [".data"]}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "test" in result

    async def test_execute_pipeline_with_initial_input(self):
        """Test pipeline with initial_input parameter."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "command", "command": "grep", "args": ["world"]}
        ]

        result = await engine.execute_pipeline(pipeline, initial_input="hello world\ntest")

        assert "hello world" in result
        assert "test" not in result

    async def test_execute_pipeline_with_buffers(self):
        """Test pipeline with save_to and read_buffers."""
        mock_caller = AsyncMock(return_value=MockToolResult("saved data"))
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "tool", "name": "fetch", "server": "http", "args": {}, "save_to": "buffer1"},
            {"type": "command", "command": "echo", "args": ["other data"], "save_to": "buffer2"},
            {"type": "read_buffers", "buffers": ["buffer1", "buffer2"]}
        ]

        result = await engine.execute_pipeline(pipeline)

        # Result should be JSON with both buffers
        parsed = json.loads(result)
        assert "buffer1" in parsed
        assert "buffer2" in parsed
        assert "saved data" in parsed["buffer1"]
        assert "other data" in parsed["buffer2"]

    async def test_execute_pipeline_read_nonexistent_buffer(self):
        """Test read_buffers with non-existent buffer raises error."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "read_buffers", "buffers": ["nonexistent"]}
        ]

        result = await engine.execute_pipeline(pipeline)

        # Should return error message
        assert "Pipeline execution failed" in result
        assert "not found" in result

    async def test_execute_pipeline_invalid_command(self):
        """Test pipeline with invalid command."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "command", "command": "rm", "args": ["-rf", "/"]}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "not allowed" in result

    async def test_execute_pipeline_missing_command_field(self):
        """Test pipeline with missing command field."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "command", "args": ["test"]}  # Missing "command" field
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "missing 'command' field" in result

    async def test_execute_pipeline_missing_tool_fields(self):
        """Test pipeline with missing tool fields."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Missing "name" field
        pipeline = [
            {"type": "tool", "server": "test_server", "args": {}}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "missing 'name' field" in result

    async def test_execute_pipeline_invalid_args_type(self):
        """Test pipeline with invalid args type (not a list)."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "command", "command": "echo", "args": "not-a-list"}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "must be an array" in result

    async def test_execute_pipeline_unknown_stage_type(self):
        """Test pipeline with unknown stage type."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "unknown_type", "data": "test"}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "Unknown pipeline item type" in result

    async def test_execute_pipeline_empty_pipeline(self):
        """Test pipeline with no stages."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = []

        result = await engine.execute_pipeline(pipeline, initial_input="test input")

        assert result == "test input"

    async def test_execute_pipeline_for_each_tool(self):
        """Test pipeline with for_each tool stage."""
        call_count = 0

        async def mock_caller(server, tool, args):
            nonlocal call_count
            call_count += 1
            return MockToolResult(f"result {call_count}")

        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "command", "command": "echo", "args": ['{"url":"u1"}\n{"url":"u2"}\n{"url":"u3"}']},
            {"type": "tool", "name": "fetch", "server": "http", "for_each": True}
        ]

        result = await engine.execute_pipeline(pipeline)

        # Should have called tool 3 times
        assert call_count == 3
        assert "result 1" in result
        assert "result 2" in result
        assert "result 3" in result


@pytest.mark.asyncio
class TestErrorHandling:
    """Test error handling and edge cases."""

    async def test_tool_caller_exception(self):
        """Test that tool caller exceptions are properly propagated."""
        async def failing_caller(server, tool, args):
            raise ValueError("Tool call failed")

        engine = ShellEngine(tool_caller=failing_caller)

        pipeline = [
            {"type": "tool", "name": "test", "server": "test", "args": {}}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "Tool call failed" in result

    async def test_stage_error_includes_stage_number(self):
        """Test that errors include the stage number."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "command", "command": "echo", "args": ["ok"]},
            {"type": "command", "command": "rm", "args": ["-rf", "/"]},  # Stage 2 - forbidden
            {"type": "command", "command": "echo", "args": ["never reached"]}
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "Stage 2" in result

    async def test_read_buffers_missing_buffers_field(self):
        """Test read_buffers without buffers field."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "read_buffers"}  # Missing "buffers" field
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "missing 'buffers' field" in result
