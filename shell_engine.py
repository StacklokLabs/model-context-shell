"""
Shell Engine - Pipeline execution engine for coordinating tool calls and shell commands.

This module provides a reusable engine for executing pipelines of shell commands and tool calls.
It is decoupled from any specific MCP implementation and uses dependency injection for tool calling.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Generator, Iterable
from pathlib import Path
from typing import Any

import headson

from models import CommandStage, PipelineStage, PreviewStage, ToolStage


def _running_in_container() -> bool:
    """Detect if we're running inside a container (Docker, Podman, etc.).

    Uses multiple detection methods:
    1. Check for /.dockerenv file (Docker-specific)
    2. Check for /run/.containerenv file (Podman-specific)
    3. Check cgroup for container indicators
    """
    # Docker creates this file
    if Path("/.dockerenv").exists():
        return True

    # Podman creates this file
    if Path("/run/.containerenv").exists():
        return True

    # Check cgroup for container indicators
    try:
        cgroup_path = Path("/proc/1/cgroup")
        if cgroup_path.exists():
            cgroup_content = cgroup_path.read_text()
            # Look for docker, podman, containerd, or lxc indicators
            if any(
                indicator in cgroup_content
                for indicator in ["docker", "podman", "containerd", "lxc", "kubepods"]
            ):
                return True
    except (OSError, PermissionError):
        pass

    return False


# Allowlist of shell commands
# Note: Commands that only generate hardcoded text (echo, printf) are excluded
# to enforce tool-first architecture where all data comes from real sources
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
    "date",
    "bc",
    "paste",
    "shuf",
    "join",
    "sleep",  # For testing timeout functionality
]

# Default timeout for shell commands (30 seconds)
# This prevents commands from hanging forever while being reasonable for most operations
DEFAULT_TIMEOUT = 30.0


class ShellEngine:
    """
    Pipeline execution engine for coordinating tool calls and shell commands.

    This engine executes pipelines of shell commands and tool calls, streaming data
    between stages. It uses dependency injection for the tool calling mechanism,
    making it reusable across different contexts (MCP, testing, etc.).
    """

    def __init__(
        self,
        tool_caller: Callable[[str, str, dict[str, Any]], Awaitable[Any]],
        batch_tool_caller: Callable[
            [str, str, list[dict[str, Any]]], Awaitable[list[Any]]
        ]
        | None = None,
        allowed_commands: list[str] | None = None,
        default_timeout: float | None = None,
    ):
        """
        Initialize the ShellEngine.

        Args:
            tool_caller: Async function that calls external tools.
                         Signature: async def(server: str, tool: str, args: dict) -> Any
            batch_tool_caller: Optional async function for batch tool calls (connection reuse).
                         Signature: async def(server: str, tool: str, args_list: list[dict]) -> list[Any]
                         If not provided, for_each mode will fall back to calling tool_caller in a loop.
            allowed_commands: List of allowed shell commands. Defaults to ALLOWED_COMMANDS.
            default_timeout: Default timeout in seconds for shell commands. Defaults to DEFAULT_TIMEOUT (30s).
        """
        self.tool_caller = tool_caller
        self.batch_tool_caller = batch_tool_caller
        self.allowed_commands = allowed_commands or ALLOWED_COMMANDS
        self.default_timeout = (
            default_timeout if default_timeout is not None else DEFAULT_TIMEOUT
        )
        # Container detection: skip bwrap when already running in Docker/Podman
        # since the container provides isolation
        self.in_container = _running_in_container()

        # Bubblewrap integration: required unless running in a container
        self.bwrap_path = shutil.which("bwrap")
        if not self.bwrap_path and not self.in_container:
            raise FileNotFoundError(
                "bubblewrap (bwrap) is required but was not found in PATH"
            )

    def _bwrap_prefix(self) -> list[str]:
        """Build the bubblewrap prefix for sandboxed command execution.

        Returns empty list when running in a container, since the container
        itself provides isolation.
        """
        # Skip bwrap when running in a container
        if self.in_container:
            return []

        if not self.bwrap_path:
            raise FileNotFoundError(
                "bubblewrap (bwrap) is required but was not found in PATH"
            )

        prefix: list[str] = [
            self.bwrap_path,
            "--unshare-all",
            "--new-session",
            "--die-with-parent",
            "--dir",
            "/",
            "--chmod",
            "0555",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--chdir",
            "/tmp",
        ]

        # Read-only bind common system locations needed for typical dynamic binaries
        for path in ("/usr", "/bin", "/lib", "/lib64"):
            if os.path.exists(path):
                prefix.extend(["--ro-bind", path, path])

        return prefix

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
        for_each: bool = False,
        timeout: float | None = None,
    ) -> Generator[str]:
        """Run a shell command as a streaming stage, consuming upstream lazily."""
        # Validate and set timeout
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        actual_timeout = timeout if timeout is not None else self.default_timeout

        # Build command list for subprocess (shell=False for security)
        # Wrap with bubblewrap for sandboxing when not in a container
        # With bwrap: bwrap [args...] -- cmd [args...]; Without: just cmd [args...]
        bwrap_prefix = self._bwrap_prefix()
        cmd_list = bwrap_prefix + ["--", cmd] + args if bwrap_prefix else [cmd] + args

        if for_each:
            # Execute command once per input line, streaming from upstream
            # Buffer to accumulate partial lines
            buffer = ""

            for chunk in upstream:
                # Add chunk to buffer
                buffer += chunk

                # Process all complete lines in buffer
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)

                    if not line.strip():
                        continue

                    proc = subprocess.Popen(
                        cmd_list,
                        shell=False,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )

                    # Write single line and get output with timeout
                    try:
                        stdout, stderr = proc.communicate(
                            input=line + "\n", timeout=actual_timeout
                        )
                        # If command failed with no output and has stderr, raise error
                        # This catches real errors (like jq parse failures) but allows
                        # commands like grep to return exit 1 for "no match" without error
                        if (
                            proc.returncode != 0
                            and not stdout.strip()
                            and stderr.strip()
                        ):
                            raise RuntimeError(
                                f"Command '{cmd}' failed with exit code {proc.returncode}. "
                                f"Stderr: {stderr.strip()}"
                            )
                        for output_line in stdout.splitlines(keepends=True):
                            yield output_line
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                        raise TimeoutError(
                            f"Command '{cmd}' timed out after {actual_timeout} seconds"
                        )

            # Process any remaining data in buffer (line without trailing newline)
            if buffer.strip():
                proc = subprocess.Popen(
                    cmd_list,
                    shell=False,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                try:
                    stdout, stderr = proc.communicate(
                        input=buffer + "\n", timeout=actual_timeout
                    )
                    # If command failed with no output and has stderr, raise error
                    # This catches real errors (like jq parse failures) but allows
                    # commands like grep to return exit 1 for "no match" without error
                    if proc.returncode != 0 and not stdout.strip() and stderr.strip():
                        raise RuntimeError(
                            f"Command '{cmd}' failed with exit code {proc.returncode}. "
                            f"Stderr: {stderr.strip()}"
                        )
                    for output_line in stdout.splitlines(keepends=True):
                        yield output_line
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise TimeoutError(
                        f"Command '{cmd}' timed out after {actual_timeout} seconds"
                    )
        else:
            # Execute command once with all input
            proc = subprocess.Popen(
                cmd_list,
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Collect all upstream data
            input_data = "".join(upstream)

            # Use communicate with timeout for proper timeout handling
            try:
                stdout, stderr = proc.communicate(
                    input=input_data, timeout=actual_timeout
                )
                # If command failed with no output and has stderr, raise error
                # This catches cases like jq parse errors where the command produces
                # error output on stderr but nothing on stdout, while allowing
                # commands like grep to return exit 1 for "no match" without error
                if proc.returncode != 0 and not stdout.strip() and stderr.strip():
                    raise RuntimeError(
                        f"Command '{cmd}' failed with exit code {proc.returncode}. "
                        f"Stderr: {stderr.strip()}"
                    )
                # Yield all output lines
                for line in stdout.splitlines(keepends=True):
                    yield line
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise TimeoutError(
                    f"Command '{cmd}' timed out after {actual_timeout} seconds"
                )

    async def tool_stage(
        self,
        server: str,
        tool: str,
        args: dict,
        upstream: Iterable[str],
        for_each: bool = False,
    ) -> str:
        """Call a tool with upstream data as input."""

        if for_each:
            # First, collect and parse all input lines
            all_call_args = []
            buffer = ""
            line_num = 0

            for chunk in upstream:
                buffer += chunk

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line_num += 1

                    if not line.strip():
                        continue

                    try:
                        parsed_line = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ValueError(
                            f"Line {line_num}: Invalid JSON in for_each mode. "
                            f"Tools with for_each require JSONL input (one JSON object per line). "
                            f"Got: {line[:100]}... "
                            f"Use jq to structure your data correctly. "
                            f"For example, if the tool needs 'url' parameter: jq -c '.[] | {{url: .}}'"
                        ) from e

                    if isinstance(parsed_line, dict):
                        call_args = {**parsed_line, **args}
                    else:
                        raise ValueError(
                            f"Line {line_num}: Expected JSON object, got {type(parsed_line).__name__}. "
                            f"Tools require parameter names. Got: {json.dumps(parsed_line)[:100]}... "
                            f"Transform your data into objects, e.g.: jq -c '{{param_name: .}}'"
                        )

                    all_call_args.append((line_num, call_args))

            # Process remaining buffer
            if buffer.strip():
                line_num += 1
                line = buffer

                try:
                    parsed_line = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Line {line_num}: Invalid JSON in for_each mode. "
                        f"Tools with for_each require JSONL input (one JSON object per line). "
                        f"Got: {line[:100]}... "
                        f"Use jq to structure your data correctly. "
                        f"For example, if the tool needs 'url' parameter: jq -c '.[] | {{url: .}}'"
                    ) from e

                if isinstance(parsed_line, dict):
                    call_args = {**parsed_line, **args}
                else:
                    raise ValueError(
                        f"Line {line_num}: Expected JSON object, got {type(parsed_line).__name__}. "
                        f"Tools require parameter names. Got: {json.dumps(parsed_line)[:100]}... "
                        f"Transform your data into objects, e.g.: jq -c '{{param_name: .}}'"
                    )

                all_call_args.append((line_num, call_args))

            # Now execute all tool calls
            results = []

            if self.batch_tool_caller and all_call_args:
                # Use batch caller for connection reuse (much faster)
                args_only = [ca[1] for ca in all_call_args]
                try:
                    batch_results = await self.batch_tool_caller(
                        server, tool, args_only
                    )
                    for result in batch_results:
                        if hasattr(result, "content"):
                            for content_item in result.content:
                                if hasattr(content_item, "text"):
                                    results.append(content_item.text)
                        else:
                            results.append(str(result))
                except Exception as e:
                    # Unwrap nested exceptions to get the root cause
                    error_msg = str(e)
                    cause = e.__cause__
                    while cause:
                        error_msg = str(cause)
                        cause = cause.__cause__
                    raise RuntimeError(
                        f"Batch tool call failed for {server}/{tool}. "
                        f"Error: {error_msg}"
                    ) from e
            else:
                # Fallback: call tool one by one (slower, opens connection per call)
                for line_num, call_args in all_call_args:
                    try:
                        result = await self.tool_caller(server, tool, call_args)
                    except Exception as e:
                        error_msg = str(e)
                        cause = e.__cause__
                        while cause:
                            error_msg = str(cause)
                            cause = cause.__cause__
                        raise RuntimeError(
                            f"Line {line_num}: Tool call failed for {server}/{tool}. "
                            f"Args used: {json.dumps(call_args, indent=2)}. "
                            f"Error: {error_msg}"
                        ) from e

                    if hasattr(result, "content"):
                        for content_item in result.content:
                            if hasattr(content_item, "text"):
                                results.append(content_item.text)
                    else:
                        results.append(str(result))

            return "\n".join(results)

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
            if hasattr(result, "content"):
                for content_item in result.content:
                    if hasattr(content_item, "text"):
                        return content_item.text

            # Fallback to string representation
            return str(result)

    async def execute_pipeline(self, pipeline: list[PipelineStage]) -> str:
        """
        Execute a pipeline of tool calls and shell commands.

        Args:
            pipeline: List of typed pipeline stages

        Returns:
            Final output of the pipeline
        """
        try:
            # Start with empty upstream - first stage must be a tool call
            upstream: Iterable[str] = iter([])

            # Process each stage in the pipeline
            for idx, stage in enumerate(pipeline):
                if isinstance(stage, CommandStage):
                    try:
                        # Validate command before execution
                        self.validate_command(stage.command)
                        upstream = self.shell_stage(
                            stage.command,
                            stage.args,
                            upstream,
                            for_each=stage.for_each,
                            timeout=stage.timeout,
                        )
                    except Exception as e:
                        raise RuntimeError(
                            f"Stage {idx + 1} (command) failed: {str(e)}"
                        )

                elif isinstance(stage, ToolStage):
                    try:
                        # Tool stages consume all upstream and return a result
                        result = await self.tool_stage(
                            stage.server,
                            stage.name,
                            stage.args,
                            upstream,
                            for_each=stage.for_each,
                        )
                        # Convert result back to a stream for next stage
                        # Ensure result ends with newline for proper shell command processing
                        if result and not result.endswith("\n"):
                            result += "\n"

                        upstream = iter([result])
                    except Exception as e:
                        raise RuntimeError(
                            f"Stage {idx + 1} (tool {stage.server}/{stage.name}) failed: {str(e)}"
                        )

                elif isinstance(stage, PreviewStage):
                    # Preview stage: summarize upstream data for the agent to inspect
                    # Uses headson to create a structure-aware preview within a char budget
                    # Output is NOT valid JSON - it uses pseudo-format with /* N more */ markers
                    try:
                        # Collect upstream data
                        input_data = "".join(upstream)

                        # Generate preview using headson with detailed style
                        # detailed style shows /* N more */ markers so agent knows data was truncated
                        preview = headson.summarize(
                            input_data,
                            format="json",
                            style="detailed",
                            input_format="json",
                            byte_budget=stage.chars,  # headson uses byte_budget param
                        )

                        # Add clear marker that this is a preview, not real data
                        preview_output = (
                            "=== PREVIEW (not valid JSON, showing structure only) ===\n"
                            f"{preview}\n"
                            "=== END PREVIEW ===\n"
                        )

                        upstream = iter([preview_output])
                    except Exception as e:
                        raise RuntimeError(
                            f"Stage {idx + 1} (preview) failed: {str(e)}"
                        )

            # Collect final output
            output = "".join(upstream)
            return output

        except Exception as e:
            # Re-raise so MCP layer sets isError=True in the response
            # This ensures clients properly display/handle the error
            raise RuntimeError(f"Pipeline execution failed: {str(e)}") from e
