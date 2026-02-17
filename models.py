"""Pydantic models for pipeline stages.

These models generate a discriminated-union JSON Schema so that MCP clients
and agents can validate pipelines before sending them.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ToolStage(BaseModel):
    """Call an external tool from an MCP server."""

    type: Literal["tool"]
    name: str = Field(min_length=1)
    server: str = Field(min_length=1)
    args: dict = Field(default_factory=dict)
    for_each: bool = False


class CommandStage(BaseModel):
    """Run an allowed shell command."""

    type: Literal["command"]
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    for_each: bool = False
    timeout: float | None = None


class PreviewStage(BaseModel):
    """Summarize upstream data for inspection."""

    type: Literal["preview"]
    chars: int = Field(default=3000, gt=0)


PipelineStage = Annotated[
    ToolStage | CommandStage | PreviewStage, Field(discriminator="type")
]
