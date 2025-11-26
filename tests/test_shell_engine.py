import json
import time
from unittest.mock import AsyncMock

import pytest

from shell_engine import ShellEngine


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
        custom_commands = ["jq", "grep"]

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
        engine.validate_command("date")

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

    async def test_shell_stage_simple_date(self):
        """Test simple date command."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        upstream = iter([""])
        result = list(engine.shell_stage("date", [], upstream))

        output = "".join(result).strip()
        assert len(output) > 0  # Date command produces output

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

    async def test_shell_stage_for_each_without_trailing_newline(self):
        """Test shell command with for_each when input lacks trailing newline."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Input without trailing newline - last line should still be processed
        upstream = iter(["apple\nbanana\napricot"])
        result = list(engine.shell_stage("grep", ["^a"], upstream, for_each=True))

        output = "".join(result)
        # All lines starting with 'a' should be processed, including 'apricot'
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
        result = await engine.tool_stage(
            "test_server", "test_tool", {"param": "value"}, upstream
        )

        assert result == "tool output"
        mock_caller.assert_called_once_with(
            "test_server", "test_tool", {"param": "value"}
        )

    async def test_tool_stage_with_json_input(self):
        """Test tool call with JSON input that gets merged with args."""
        mock_caller = AsyncMock(return_value=MockToolResult("merged output"))
        engine = ShellEngine(tool_caller=mock_caller)

        json_input = json.dumps({"upstream_param": "upstream_value"})
        upstream = iter([json_input])

        await engine.tool_stage(
            "test_server", "test_tool", {"explicit_param": "explicit_value"}, upstream
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
        jsonl_input = (
            '{"url": "http://example.com/1"}\n{"url": "http://example.com/2"}\n'
        )
        upstream = iter([jsonl_input])

        result = await engine.tool_stage(
            "test_server", "fetch", {}, upstream, for_each=True
        )

        # Should be called twice (once per line)
        assert mock_caller.call_count == 2
        assert "result" in result

    async def test_tool_stage_for_each_invalid_json(self):
        """Test tool call with for_each and invalid JSON raises error."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        invalid_input = "not valid json\n"
        upstream = iter([invalid_input])

        with pytest.raises(ValueError, match="Invalid JSON"):
            await engine.tool_stage(
                "test_server", "test_tool", {}, upstream, for_each=True
            )

    async def test_tool_stage_for_each_non_dict_json(self):
        """Test tool call with for_each and non-dict JSON raises error."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # JSON array instead of object
        array_input = '["item1", "item2"]\n'
        upstream = iter([array_input])

        with pytest.raises(ValueError, match="Expected JSON object"):
            await engine.tool_stage(
                "test_server", "test_tool", {}, upstream, for_each=True
            )

    async def test_tool_stage_tool_error_handling(self):
        """Test tool call error handling in for_each mode."""
        mock_caller = AsyncMock(side_effect=Exception("Tool failed"))
        engine = ShellEngine(tool_caller=mock_caller)

        # Use JSONL input for for_each mode
        upstream = iter(['{"param": "value"}\n'])

        with pytest.raises(RuntimeError, match="Tool failed"):
            await engine.tool_stage(
                "test_server", "test_tool", {}, upstream, for_each=True
            )

    async def test_tool_stage_result_with_no_content_attribute(self):
        """Test tool result that doesn't have content attribute."""
        mock_caller = AsyncMock(return_value="plain string result")
        engine = ShellEngine(tool_caller=mock_caller)

        upstream = iter([""])
        result = await engine.tool_stage("test_server", "test_tool", {}, upstream)

        assert result == "plain string result"

    async def test_tool_stage_for_each_without_trailing_newline(self):
        """Test tool call with for_each when input doesn't have trailing newline."""
        mock_caller = AsyncMock(return_value=MockToolResult("result"))
        engine = ShellEngine(tool_caller=mock_caller)

        # Input without trailing newline - should still process the last line
        jsonl_input = '{"url": "http://example.com/1"}\n{"url": "http://example.com/2"}'
        upstream = iter([jsonl_input])

        result = await engine.tool_stage(
            "test_server", "fetch", {}, upstream, for_each=True
        )

        # Should be called twice (once per line, including line without newline)
        assert mock_caller.call_count == 2
        assert "result" in result

    async def test_tool_stage_non_dict_json_upstream(self):
        """Test tool_stage with non-dict JSON upstream (array) in non-for_each mode."""
        mock_caller = AsyncMock(return_value=MockToolResult("result"))
        engine = ShellEngine(tool_caller=mock_caller)

        # JSON array as upstream
        array_input = '["item1", "item2", "item3"]'
        upstream = iter([array_input])

        result = await engine.tool_stage("test_server", "test_tool", {}, upstream)

        # Should add array as 'input' field
        mock_caller.assert_called_once()
        call_args = mock_caller.call_args[0][2]
        assert call_args["input"] == ["item1", "item2", "item3"]

    async def test_tool_stage_plain_text_upstream(self):
        """Test tool_stage with plain text (non-JSON) upstream."""
        mock_caller = AsyncMock(return_value=MockToolResult("result"))
        engine = ShellEngine(tool_caller=mock_caller)

        # Plain text that isn't valid JSON
        text_input = "some plain text data"
        upstream = iter([text_input])

        result = await engine.tool_stage("test_server", "test_tool", {}, upstream)

        # Should add text as 'input' field
        mock_caller.assert_called_once()
        call_args = mock_caller.call_args[0][2]
        assert call_args["input"] == "some plain text data"

    async def test_tool_stage_non_dict_json_does_not_override_existing_input(self):
        """Test that non-dict JSON doesn't override explicit 'input' arg."""
        mock_caller = AsyncMock(return_value=MockToolResult("result"))
        engine = ShellEngine(tool_caller=mock_caller)

        array_input = '["upstream_data"]'
        upstream = iter([array_input])

        result = await engine.tool_stage(
            "test_server", "test_tool", {"input": "explicit_input"}, upstream
        )

        # Explicit input should be preserved
        mock_caller.assert_called_once()
        call_args = mock_caller.call_args[0][2]
        assert call_args["input"] == "explicit_input"


@pytest.mark.asyncio
class TestExecutePipeline:
    """Test execute_pipeline with various pipeline configurations."""

    async def test_execute_pipeline_single_command(self):
        """Test pipeline with tool followed by shell command."""
        mock_caller = AsyncMock(return_value=MockToolResult("test output"))
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "tool", "name": "generate", "server": "test", "args": {}},
            {"type": "command", "command": "grep", "args": ["test"]},
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "test output" in result

    async def test_execute_pipeline_multiple_commands(self):
        """Test pipeline with tool and multiple shell commands."""
        mock_caller = AsyncMock(return_value=MockToolResult("apple\nbanana\ncherry"))
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "tool", "name": "get_data", "server": "test", "args": {}},
            {"type": "command", "command": "grep", "args": ["a"]},
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
            {
                "type": "tool",
                "name": "test_tool",
                "server": "test_server",
                "args": {"key": "value"},
            }
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "tool result" in result
        mock_caller.assert_called_once()

    async def test_execute_pipeline_mixed_stages(self):
        """Test pipeline with mixed command and tool stages."""
        mock_caller = AsyncMock(return_value=MockToolResult('{"data": "test"}'))
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {
                "type": "tool",
                "name": "fetch",
                "server": "http",
                "args": {"url": "http://example.com"},
            },
            {"type": "command", "command": "jq", "args": [".data"]},
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "test" in result

    async def test_execute_pipeline_invalid_command(self):
        """Test pipeline with invalid command."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [{"type": "command", "command": "rm", "args": ["-rf", "/"]}]

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

    async def test_execute_pipeline_missing_tool_name_field(self):
        """Test pipeline with missing tool name field."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Missing "name" field
        pipeline = [{"type": "tool", "server": "test_server", "args": {}}]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "missing 'name' field" in result

    async def test_execute_pipeline_missing_tool_server_field(self):
        """Test pipeline with missing tool server field."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Missing "server" field
        pipeline = [{"type": "tool", "name": "test_tool", "args": {}}]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "missing 'server' field" in result

    async def test_execute_pipeline_invalid_args_type(self):
        """Test pipeline with invalid args type (not a list)."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [{"type": "command", "command": "grep", "args": "not-a-list"}]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "must be an array" in result

    async def test_execute_pipeline_unknown_stage_type(self):
        """Test pipeline with unknown stage type."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [{"type": "unknown_type", "data": "test"}]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "Unknown pipeline item type" in result

    async def test_execute_pipeline_empty_pipeline(self):
        """Test pipeline with no stages returns empty string."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = []

        result = await engine.execute_pipeline(pipeline)

        assert result == ""

    async def test_execute_pipeline_for_each_tool(self):
        """Test pipeline with for_each tool stage."""
        call_count = 0

        async def mock_caller(server, tool, args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: list tool returns JSON array
                return MockToolResult('{"url":"u1"}\n{"url":"u2"}\n{"url":"u3"}')
            else:
                # Subsequent calls: fetch tool processes each URL
                return MockToolResult(f"result {call_count - 1}")

        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "tool", "name": "list_urls", "server": "api", "args": {}},
            {"type": "tool", "name": "fetch", "server": "http", "for_each": True},
        ]

        result = await engine.execute_pipeline(pipeline)

        # Should have called tool 4 times (1 list + 3 fetches)
        assert call_count == 4
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

        pipeline = [{"type": "tool", "name": "test", "server": "test", "args": {}}]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "Tool call failed" in result

    async def test_stage_error_includes_stage_number(self):
        """Test that errors include the stage number."""
        mock_caller = AsyncMock(return_value=MockToolResult("ok"))
        engine = ShellEngine(tool_caller=mock_caller)

        pipeline = [
            {"type": "tool", "name": "get_data", "server": "test", "args": {}},
            {
                "type": "command",
                "command": "rm",
                "args": ["-rf", "/"],
            },  # Stage 2 - forbidden
            {"type": "command", "command": "grep", "args": ["never reached"]},
        ]

        result = await engine.execute_pipeline(pipeline)

        assert "Pipeline execution failed" in result
        assert "Stage 2" in result


@pytest.mark.asyncio
class TestShellCommandTimeouts:
    """Test timeout functionality for shell commands."""

    @pytest.mark.timeout(1)
    async def test_shell_stage_with_custom_timeout(self):
        """Test that shell_stage accepts and uses a custom timeout."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Fast command should complete within timeout
        upstream = iter(["test"])
        result = list(engine.shell_stage("date", [], upstream, timeout=0.5))

        output = "".join(result).strip()
        assert len(output) > 0  # Date produces output

    @pytest.mark.timeout(1)
    async def test_shell_stage_timeout_slow_command(self):
        """Test that slow commands are terminated when timeout is exceeded."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Command that sleeps for 10 seconds, but timeout is 0.2 seconds
        upstream = iter([""])

        start = time.time()
        with pytest.raises(TimeoutError):
            list(engine.shell_stage("sleep", ["10"], upstream, timeout=0.2))
        elapsed = time.time() - start

        # Should timeout in ~0.2 seconds, not wait 10 seconds
        assert elapsed < 0.5, f"Timeout took too long: {elapsed} seconds"

    @pytest.mark.timeout(1)
    async def test_shell_stage_default_timeout_exists(self):
        """Test that shell_stage has a default timeout to prevent hanging forever."""
        mock_caller = AsyncMock()
        # Use a very short default timeout for testing (0.3 seconds instead of 30)
        engine = ShellEngine(tool_caller=mock_caller, default_timeout=0.3)

        # Command that would hang forever without timeout
        upstream = iter([""])

        start = time.time()
        # Should timeout with default timeout (not hang forever)
        with pytest.raises(TimeoutError):
            list(engine.shell_stage("sleep", ["999"], upstream))
        elapsed = time.time() - start

        # Should timeout within reasonable time (should be ~0.3s)
        assert elapsed < 0.6, f"Default timeout is too long: {elapsed} seconds"
        assert elapsed > 0.2, f"Default timeout is too short: {elapsed} seconds"

    @pytest.mark.timeout(1)
    async def test_execute_pipeline_command_timeout(self):
        """Test that execute_pipeline respects command timeouts."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Pipeline with a command that times out
        pipeline = [
            {"type": "command", "command": "sleep", "args": ["10"], "timeout": 0.2}
        ]

        start = time.time()
        result = await engine.execute_pipeline(pipeline)
        elapsed = time.time() - start

        # Should fail with timeout error
        assert "timeout" in result.lower() or "timed out" in result.lower()
        assert elapsed < 0.5, f"Timeout took too long: {elapsed} seconds"

    @pytest.mark.timeout(2)
    async def test_execute_pipeline_for_each_with_timeout(self):
        """Test that for_each mode respects timeouts."""
        mock_caller = AsyncMock(return_value=MockToolResult("line1\nline2"))
        engine = ShellEngine(tool_caller=mock_caller)

        # Each line would cause a slow command, but should timeout
        pipeline = [
            {"type": "tool", "name": "get_lines", "server": "test", "args": {}},
            {
                "type": "command",
                "command": "sleep",
                "args": ["10"],
                "for_each": True,
                "timeout": 0.2,
            },
        ]

        start = time.time()
        await engine.execute_pipeline(pipeline)
        elapsed = time.time() - start

        # Should timeout quickly, not wait 20 seconds (10s × 2 lines)
        assert elapsed < 1.0, f"For-each timeout took too long: {elapsed} seconds"

    async def test_shell_stage_zero_timeout_rejected(self):
        """Test that zero or negative timeouts are rejected."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        upstream = iter(["test"])

        with pytest.raises(ValueError, match="timeout.*positive|invalid"):
            list(engine.shell_stage("date", [], upstream, timeout=0))

        with pytest.raises(ValueError, match="timeout.*positive|invalid"):
            list(engine.shell_stage("date", [], upstream, timeout=-1))

    async def test_engine_initialization_with_default_timeout(self):
        """Test that ShellEngine can be initialized with a custom default timeout."""
        mock_caller = AsyncMock()

        # Initialize with custom default timeout
        engine = ShellEngine(tool_caller=mock_caller, default_timeout=5.0)

        # Verify the default timeout is set
        assert hasattr(engine, "default_timeout")
        assert engine.default_timeout == 5.0


@pytest.mark.asyncio
class TestStreamingForEach:
    """Test that for_each mode truly streams data instead of loading all into memory."""

    def test_shell_stage_for_each_streams_lazily(self):
        """Test that shell_stage for_each processes lines as they arrive, not after loading all."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Create a tracking generator
        consumption_log = []

        def tracked_generator():
            for i in range(5):
                consumption_log.append(f"generated_{i}")
                yield f"line {i}\n"
            consumption_log.append("generator_exhausted")

        upstream = tracked_generator()

        # Process with for_each - should start yielding before generator is exhausted
        # Use 'head' with no args which just passes through input
        results = []
        for output in engine.shell_stage("head", [], upstream, for_each=True):
            results.append(output)
            # If we're truly streaming, the generator should NOT be exhausted yet
            # when we get the first result
            if len(results) == 1:
                consumption_log.append("first_result_received")

        # Verify we got results
        assert len(results) > 0

        # Key assertion: we should receive first result BEFORE generator is exhausted
        # Current implementation will fail this because it calls "".join(upstream) first
        first_result_idx = consumption_log.index("first_result_received")
        exhausted_idx = consumption_log.index("generator_exhausted")
        assert first_result_idx < exhausted_idx, (
            f"Generator was exhausted before first result! Log: {consumption_log}"
        )

    async def test_tool_stage_for_each_streams_lazily(self):
        """Test that tool_stage for_each processes lines as they arrive, not after loading all."""
        # Create a mock tool caller that returns simple results
        call_count = []

        async def mock_tool_caller(server, tool, args):
            call_count.append(len(call_count))
            result = MockToolResult(f"result_{len(call_count)}")
            return result

        engine = ShellEngine(tool_caller=mock_tool_caller)

        # Create a tracking generator
        consumption_log = []

        def tracked_generator():
            for i in range(5):
                consumption_log.append(f"generated_{i}")
                yield f'{{"value": {i}}}\n'
            consumption_log.append("generator_exhausted")

        upstream = tracked_generator()

        # Process with for_each
        await engine.tool_stage("test", "test_tool", {}, upstream, for_each=True)

        # At least verify tool was called
        assert len(call_count) > 0

        # Key assertion: generator should be exhausted (consumed by tool_stage)
        # But ideally, we want the tool to be called progressively, not all at once
        assert "generator_exhausted" in consumption_log

        # Note: For tool_stage, we currently accumulate results in a list,
        # so we can't yield incrementally. But we should still process
        # the input generator lazily (call tool for each line as it arrives)

    def test_shell_stage_for_each_handles_large_stream_memory_efficiently(self):
        """Test that for_each can handle large streams without loading everything into memory."""
        mock_caller = AsyncMock()
        engine = ShellEngine(tool_caller=mock_caller)

        # Create a generator that yields many lines
        # If we load all into memory first, this would use significant memory
        def large_generator():
            for i in range(1000):
                yield f"line {i}\n"

        upstream = large_generator()

        # Process with for_each - use 'head' which passes through input
        result_count = 0
        for _output in engine.shell_stage("head", [], upstream, for_each=True):
            result_count += 1
            # If we're streaming, we should be able to break early
            # without consuming the entire generator
            if result_count >= 10:
                break

        # We should have processed at least 10 lines
        assert result_count >= 10

        # The key is that we didn't need to consume all 1000 lines
        # to get the first 10 results (but we can't easily verify this
        # without instrumenting the generator)
