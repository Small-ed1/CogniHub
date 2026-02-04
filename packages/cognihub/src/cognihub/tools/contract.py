from __future__ import annotations

from typing import Any, Dict, List, Literal, Union
from pydantic import BaseModel, Field, ConfigDict


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    arguments: Dict[str, Any]


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_request"]
    id: str = Field(min_length=1, max_length=64)
    tool_calls: List[ToolCall] = Field(min_length=1, max_length=6)


class FinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["final"]
    id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=40_000)


ToolContract = Union[ToolRequest, FinalAnswer]