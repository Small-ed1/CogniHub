from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from contextharbor import config as ch_config
from contextharbor.tools.registry import ToolRegistry, ToolSpec


class ExampleTimeArgs(BaseModel):
    tz: str = Field(default="local", description="Timezone: local or utc")


class ExampleTimeOut(BaseModel):
    iso: str
    epoch_ms: int
    timezone: str


async def _example_time(args: ExampleTimeArgs) -> dict[str, Any]:
    use_utc = (args.tz or "").strip().lower() == "utc"
    now = datetime.now(timezone.utc if use_utc else None)
    iso = now.astimezone(timezone.utc).isoformat() if use_utc else now.isoformat()
    epoch_ms = int(now.timestamp() * 1000)
    return {"iso": iso, "epoch_ms": epoch_ms, "timezone": "utc" if use_utc else "local"}


def register_tools(registry: ToolRegistry, **_deps: Any) -> None:
    """Register tools with the ContextHarbor registry.

    ContextHarbor calls this at startup for every module listed in `tools.toml` under
    `[tools].plugin_modules`.

    This plugin honors `[tools].enabled` by only registering tools that are listed.
    """

    enabled = set(ch_config.config.enabled_tools or [])

    if "example_time" in enabled:
        registry.register(
            ToolSpec(
                name="example_time",
                description="Return the server's current time.",
                args_model=ExampleTimeArgs,
                handler=_example_time,
                side_effect="read_only",
                output_model=ExampleTimeOut,
                error_codes=["invalid_arguments"],
            )
        )
