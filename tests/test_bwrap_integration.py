import shutil

import pytest

from shell_engine import ShellEngine

pytestmark = pytest.mark.skipif(
    shutil.which("bwrap") is None, reason="bubblewrap not installed"
)


async def _new_engine():
    async def dummy_tool_caller(server, tool, args):
        raise RuntimeError("tool caller not used in these tests")

    return ShellEngine(tool_caller=dummy_tool_caller)


@pytest.mark.asyncio
async def test_proc_is_mounted_and_readable():
    engine = await _new_engine()

    pipeline = [
        {
            "type": "command",
            "command": "head",
            "args": ["-n", "1", "/proc/self/mountinfo"],
        }
    ]

    out = await engine.execute_pipeline(pipeline)
    assert out.strip() != ""
    # Basic sanity that it looks like a mountinfo line
    assert "/proc" in out or "/" in out or " - " in out


@pytest.mark.asyncio
async def test_tmp_is_writable_tmpfs_and_readable_within_command():
    engine = await _new_engine()

    # Use awk to write and then read back within the same process
    prog = (
        'BEGIN { f = "/tmp/mcpshell_test"; '
        'print "hello" > f; close(f); '
        "while ((getline line < f) > 0) { print line } "
        "close(f) }"
    )

    pipeline = [{"type": "command", "command": "awk", "args": [prog]}]

    out = await engine.execute_pipeline(pipeline)
    assert "hello" in out


@pytest.mark.asyncio
async def test_root_is_read_only_cannot_create_files():
    engine = await _new_engine()

    # Attempt to write to /. If it were writable, we'd read back content.
    # With proper sandboxing, awk will either fail to write (permission denied)
    # or print NOPE. Either way, WROTE should not appear.
    prog = (
        'BEGIN { f = "/mcpshell_should_fail"; '
        'print "x" > f; close(f); '
        "c = 0; while ((getline line < f) > 0) { c++ } "
        'close(f); if (c>0) { print "WROTE" } else { print "NOPE" } }'
    )

    pipeline = [{"type": "command", "command": "awk", "args": [prog]}]

    out = await engine.execute_pipeline(pipeline)
    assert "WROTE" not in out


@pytest.mark.asyncio
async def test_usr_is_read_only_cannot_create_files():
    engine = await _new_engine()

    prog = (
        'BEGIN { f = "/usr/mcpshell_should_fail"; '
        'print "x" > f; close(f); '
        "c = 0; while ((getline line < f) > 0) { c++ } "
        'close(f); if (c>0) { print "WROTE" } else { print "NOPE" } }'
    )

    pipeline = [{"type": "command", "command": "awk", "args": [prog]}]

    out = await engine.execute_pipeline(pipeline)
    assert "WROTE" not in out
