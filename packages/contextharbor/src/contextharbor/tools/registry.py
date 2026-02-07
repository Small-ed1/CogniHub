from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type
from pydantic import BaseModel


SideEffect = str  # "read_only" | "network" | "filesystem_write" | "dangerous"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Callable[[Any], Awaitable[Dict[str, Any]]]
    side_effect: SideEffect = "read_only"
    requires_confirmation: bool = False
    enabled: bool = True
    output_model: Type[BaseModel] | None = None
    error_codes: list[str] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_for_prompt(self) -> list[dict[str, str]]:
        """Minimal shape to feed the model."""
        out = []
        for t in self._tools.values():
            if t.enabled:
                out.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "side_effect": t.side_effect,
                        "requires_confirmation": str(t.requires_confirmation),
                    }
                )
        return out

    def list_schemas(self) -> list[dict[str, Any]]:
        """Stable, user-visible tool schema list for discovery."""
        out: list[dict[str, Any]] = []
        for t in self._tools.values():
            if not t.enabled:
                continue

            input_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
            if t.args_model is not None:
                input_schema = sanitize_parameters(t.args_model.model_json_schema())

            output_schema: dict[str, Any] = {"type": "object"}
            if t.output_model is not None:
                output_schema = sanitize_parameters(t.output_model.model_json_schema())

            out.append(
                {
                    "name": t.name,
                    "description": t.description,
                    "side_effect": t.side_effect,
                    "requires_confirmation": bool(t.requires_confirmation),
                    "input_schema": input_schema,
                    "output_schema": output_schema,
                    "error_codes": t.error_codes or [],
                }
            )

        return out

    def build_ollama_tools(self) -> List[Dict[str, Any]]:
        """Build Ollama-native tool format from registry (sanitized schema)."""
        out: List[Dict[str, Any]] = []

        for t in self._tools.values():
            if not t.enabled:
                continue

            params: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}

            if t.args_model is not None:
                full = t.args_model.model_json_schema()
                params = sanitize_parameters(full)

            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": params,
                    },
                }
            )

        return out


def sanitize_schema_node(node: Any, defs: Optional[Dict[str, Any]] = None) -> Any:
    if not isinstance(node, dict):
        return node

    out: Dict[str, Any] = {}
    if defs is None:
        defs = {}

    # handle $ref - resolve to actual definition
    if "$ref" in node:
        ref_path = node["$ref"]
        if ref_path.startswith("#/$defs/"):
            def_name = ref_path.split("/")[-1]
            if def_name in defs:
                return sanitize_schema_node(defs[def_name], defs)
        return {}

    # handle anyOf - take first non-null option for simplicity
    if "anyOf" in node:
        # preserve property-level description when anyOf exists
        property_desc = node.get("description") if isinstance(node.get("description"), str) else None
        
        for option in node["anyOf"]:
            if not (isinstance(option, dict) and option.get("type") == "null"):
                result = sanitize_schema_node(option, defs)
                # preserve description from parent anyOf if not in option
                if property_desc and "description" not in result:
                    result["description"] = property_desc
                return result
        return {}

    # keep core type-ish info + array constraints
    for k in ("type", "enum", "minimum", "maximum", "minLength", "maxLength", "format", 
              "pattern", "minItems", "maxItems"):
        if k in node:
            out[k] = node[k]

    # keep description (helps model call tools correctly)
    if "description" in node and isinstance(node["description"], str):
        out["description"] = node["description"]

    # arrays
    if "items" in node:
        out["items"] = sanitize_schema_node(node["items"], defs)

    # objects
    if "properties" in node and isinstance(node["properties"], dict):
        out["properties"] = {k: sanitize_schema_node(v, defs) for k, v in node["properties"].items()}

    if "required" in node and isinstance(node["required"], list):
        out["required"] = node["required"]

    return out


def sanitize_parameters(schema: Dict[str, Any]) -> Dict[str, Any]:
    defs = schema.get("$defs", {})
    return sanitize_schema_node({
        "type": "object",
        "properties": schema.get("properties", {}) or {},
        "required": schema.get("required", []) or [],
    }, defs)
