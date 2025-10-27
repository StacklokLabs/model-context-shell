"""
Shell Engine - Pipeline execution engine for coordinating tool calls and shell commands.

This module provides a reusable engine for executing pipelines of shell commands and tool calls.
It is decoupled from any specific MCP implementation and uses dependency injection for tool calling.
"""

import subprocess
import threading
from typing import Iterable, Generator, Callable, Awaitable, Any, Dict
import asyncio
import json
import tempfile
from pathlib import Path


# Whitelist of allowed shell commands
ALLOWED_COMMANDS = [
    "grep",
    "jq",
    "sort",
    "uniq",
    "cut",
    "sed",
    "awk",
    "wc",
    "head",
    "tail",
    "tr",
    "echo",
    "printf",
    "date",
    "bc",
    "paste",
    "shuf",
    "join",
]


class ShellEngine:
    """
    Pipeline execution engine for coordinating tool calls and shell commands.

    This engine executes pipelines of shell commands and tool calls, streaming data
    between stages. It uses dependency injection for the tool calling mechanism,
    making it reusable across different contexts (MCP, testing, etc.).
    """

    def __init__(
        self,
        tool_caller: Callable[[str, str, Dict[str, Any]], Awaitable[Any]],
        allowed_commands: list[str] = None
    ):
        """
        Initialize the ShellEngine.

        Args:
            tool_caller: Async function that calls external tools.
                         Signature: async def(server: str, tool: str, args: dict) -> Any
            allowed_commands: List of allowed shell commands. Defaults to ALLOWED_COMMANDS.
        """
        self.tool_caller = tool_caller
        self.allowed_commands = allowed_commands or ALLOWED_COMMANDS

    def validate_command(self, cmd: str) -> None:
        """Validate that a command is in the allowed list."""
        if not cmd:
            raise ValueError("Empty command")

        if cmd not in self.allowed_commands:
            raise ValueError(
                f"Command '{cmd}' is not allowed. "
                f"Allowed commands: {', '.join(self.allowed_commands)}"
            )

    def list_available_commands(self) -> list[str]:
        """Return the list of allowed shell commands."""
        return self.allowed_commands.copy()

    def shell_stage(
        self,
        cmd: str,
        args: list[str],
        upstream: Iterable[str],
        for_each: bool = False
    ) -> Generator[str, None, None]:
        """Run a shell command as a streaming stage, consuming upstream lazily."""
        # Build command list for subprocess (shell=False for security)
        cmd_list = [cmd] + args

        if for_each:
            # Execute command once per input line
            input_data = "".join(upstream)
            for line in input_data.strip().split('\n'):
                if not line.strip():
                    continue

                proc = subprocess.Popen(
                    cmd_list,
                    shell=False,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                # Write single line and get output
                stdout, _ = proc.communicate(input=line + '\n')
                for output_line in stdout.splitlines(keepends=True):
                    yield output_line
        else:
            # Execute command once with all input (streaming)
            proc = subprocess.Popen(
                cmd_list,
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            assert proc.stdin and proc.stdout

            # Write upstream into the process stdin in the background
            def _writer():
                try:
                    for item in upstream:
                        proc.stdin.write(item)
                    proc.stdin.close()
                except BrokenPipeError:
                    pass

            threading.Thread(target=_writer, daemon=True).start()

            # Yield stdout as it arrives
            for line in proc.stdout:
                yield line

            rc = proc.wait()

            # Like shell pipelines, we don't fail on non-zero exit codes
            # The pipeline continues and only breaks on severe errors (handled by exceptions above)

    async def tool_stage(
        self,
        server: str,
        tool: str,
        args: dict,
        upstream: Iterable[str],
        for_each: bool = False
    ) -> str:
        """Call a tool with upstream data as input."""

        if for_each:
            # Execute tool once per line (expecting JSONL input)
            results = []
            input_data = "".join(upstream)

            for line_num, line in enumerate(input_data.strip().split('\n'), 1):
                if not line.strip():
                    continue

                try:
                    # Parse each line as JSON
                    parsed_line = json.loads(line)
                except json.JSONDecodeError as e:
                    # If parsing fails, provide helpful error message
                    raise ValueError(
                        f"Line {line_num}: Invalid JSON in for_each mode. "
                        f"Tools with for_each require JSONL input (one JSON object per line). "
                        f"Got: {line[:100]}... "
                        f"Use jq to structure your data correctly. "
                        f"For example, if the tool needs 'url' parameter: jq -c '.[] | {{url: .}}'"
                    ) from e

                # Merge parsed JSON with args (args take precedence)
                if isinstance(parsed_line, dict):
                    call_args = {**parsed_line, **args}
                else:
                    # Non-dict JSON values (arrays, strings, numbers) cannot be used directly
                    raise ValueError(
                        f"Line {line_num}: Expected JSON object, got {type(parsed_line).__name__}. "
                        f"Tools require parameter names. Got: {json.dumps(parsed_line)[:100]}... "
                        f"Transform your data into objects, e.g.: jq -c '{{param_name: .}}'"
                    )

                # Call the tool
                try:
                    result = await self.tool_caller(server, tool, call_args)
                except Exception as e:
                    # Add context about which line failed
                    raise RuntimeError(
                        f"Line {line_num}: Tool call failed for {server}/{tool}. "
                        f"Args used: {json.dumps(call_args, indent=2)}. "
                        f"Error: {str(e)}"
                    ) from e

                # Extract content from result
                if hasattr(result, 'content'):
                    for content_item in result.content:
                        if hasattr(content_item, 'text'):
                            results.append(content_item.text)
                else:
                    results.append(str(result))

            return '\n'.join(results)

        else:
            # Execute tool once with all upstream data
            # Collect all upstream data
            input_data = "".join(upstream).strip()

            # If there's upstream data, try to parse it as JSON and merge with args
            if input_data:
                try:
                    parsed_input = json.loads(input_data)
                    # If parsed input is a dict, merge it with args (args take precedence)
                    if isinstance(parsed_input, dict):
                        args = {**parsed_input, **args}
                    else:
                        # If it's not a dict (e.g., array, string), add as 'input' field
                        if "input" not in args:
                            args = {**args, "input": parsed_input}
                except json.JSONDecodeError:
                    # If JSON parsing fails, treat as plain string input
                    if "input" not in args:
                        args = {**args, "input": input_data}

            # Call the tool
            result = await self.tool_caller(server, tool, args)

            # Extract content from result
            if hasattr(result, 'content'):
                for content_item in result.content:
                    if hasattr(content_item, 'text'):
                        return content_item.text

            # Fallback to string representation
            return str(result)

    async def execute_pipeline(self, pipeline: list[dict], initial_input: str = "") -> str:
        """
        Execute a pipeline of tool calls and shell commands.

        Args:
            pipeline: List of pipeline stage dictionaries
            initial_input: Initial data to feed into the pipeline

        Returns:
            Final output of the pipeline
        """
        # Create temporary directory for buffers
        with tempfile.TemporaryDirectory(prefix="mcp_pipeline_") as temp_dir:
            temp_path = Path(temp_dir)

            try:
                # Start with initial input as a generator
                upstream: Iterable[str] = iter([initial_input]) if initial_input else iter([])

                # Process each stage in the pipeline
                for idx, item in enumerate(pipeline):
                    item_type = item.get("type")
                    for_each = item.get("for_each", False)
                    save_to = item.get("save_to")

                    if item_type == "read_buffers":
                        # Special stage type: retrieve buffers and return as JSON
                        buffer_names = item.get("buffers", [])
                        if not buffer_names:
                            raise ValueError("read_buffers stage missing 'buffers' field")

                        # Collect requested buffers from disk
                        result_dict = {}
                        available_buffers = [f.stem for f in temp_path.glob("*.buf")]

                        for buffer_name in buffer_names:
                            buffer_file = temp_path / f"{buffer_name}.buf"
                            if not buffer_file.exists():
                                raise ValueError(
                                    f"Buffer '{buffer_name}' not found. "
                                    f"Available buffers: {available_buffers}"
                                )
                            result_dict[buffer_name] = buffer_file.read_text()

                        # Output as JSON and convert to stream
                        output = json.dumps(result_dict, indent=2)
                        upstream = iter([output + '\n'])

                        # Save to buffer if requested
                        if save_to:
                            (temp_path / f"{save_to}.buf").write_text(output)

                        continue

                    if item_type == "command":
                        command = item.get("command", "")
                        cmd_args = item.get("args", [])

                        if not command:
                            raise ValueError("Command stage missing 'command' field")

                        if not isinstance(cmd_args, list):
                            raise ValueError(f"Command 'args' must be an array, got {type(cmd_args).__name__}")

                        try:
                            # Validate command before execution
                            self.validate_command(command)
                            upstream = self.shell_stage(command, cmd_args, upstream, for_each=for_each)

                            # Save to buffer if requested
                            if save_to:
                                output = "".join(upstream)
                                (temp_path / f"{save_to}.buf").write_text(output)
                                # Recreate upstream for next stage
                                upstream = iter([output])
                        except Exception as e:
                            raise RuntimeError(f"Stage {idx + 1} (command) failed: {str(e)}")

                    elif item_type == "tool":
                        tool_name = item.get("name", "")
                        server_name = item.get("server", "")
                        args = item.get("args", {})

                        if not tool_name:
                            raise ValueError("Tool stage missing 'name' field")
                        if not server_name:
                            raise ValueError("Tool stage missing 'server' field")

                        try:
                            # Tool stages consume all upstream and return a result
                            result = await self.tool_stage(server_name, tool_name, args, upstream, for_each=for_each)
                            # Convert result back to a stream for next stage
                            # Ensure result ends with newline for proper shell command processing
                            if result and not result.endswith('\n'):
                                result += '\n'

                            # Save to buffer if requested
                            if save_to:
                                (temp_path / f"{save_to}.buf").write_text(result)

                            upstream = iter([result])
                        except Exception as e:
                            raise RuntimeError(f"Stage {idx + 1} (tool {server_name}/{tool_name}) failed: {str(e)}")

                    else:
                        raise ValueError(f"Unknown pipeline item type: {item_type}")

                # Collect final output
                output = "".join(upstream)
                return output

            except Exception as e:
                import traceback
                error_details = f"Pipeline execution failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
                return error_details
