from __future__ import annotations

import json
import re
from typing import Any

from steelai.research_agent import TOOL_DEFINITIONS, execute_readonly_tool


BRIDGE_NAME = "SteelAI DSH Read-Only Bridge"
BRIDGE_VERSION = "0.1.0"
MAX_RESULT_CHARACTERS = 500_000

# DSH receives the same seven tools already used by SteelAI's evaluated Research
# Agent. This bridge never accepts an arbitrary function or filesystem path.
ALLOWED_TOOLS = frozenset(
    {
        "list_samples",
        "get_sample_bundle",
        "compare_samples",
        "calculate_physics_card",
        "get_ebsd_summary",
        "get_autodimple_summary",
        "get_evidence_validation_summary",
    }
)

_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\n\r\t`\"']+")
_RAW_RESEARCH_FILE = re.compile(r"[^\s`\"']+\.(?:ctf|tif|tiff)\b", re.IGNORECASE)


class DSHBridgeError(ValueError):
    """Raised when a DSH request violates the read-only bridge contract."""


def tool_catalog() -> list[dict[str, Any]]:
    """Return only the audited tool schemas exposed to DSH."""
    return [item for item in TOOL_DEFINITIONS if item["name"] in ALLOWED_TOOLS]


def bridge_status() -> dict[str, Any]:
    """Return a keyless, path-free description of the bridge policy."""
    return {
        "name": BRIDGE_NAME,
        "version": BRIDGE_VERSION,
        "mode": "read_only_structured_data",
        "tool_count": len(tool_catalog()),
        "tools": [item["name"] for item in tool_catalog()],
        "writes_allowed": False,
        "raw_files_allowed": False,
        "absolute_paths_allowed": False,
        "api_key_required": False,
    }


def _definition(name: str) -> dict[str, Any]:
    for item in tool_catalog():
        if item["name"] == name:
            return item
    raise DSHBridgeError(f"Unknown or non-whitelisted DSH tool: {name}")


def _validate_arguments(definition: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise DSHBridgeError("Tool arguments must be a JSON object.")

    schema = definition["parameters"]
    properties = schema.get("properties", {})
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise DSHBridgeError(f"Unexpected argument(s): {', '.join(unknown)}")

    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        raise DSHBridgeError(f"Missing required argument(s): {', '.join(missing)}")

    for name, value in arguments.items():
        property_schema = properties[name]
        if property_schema.get("type") == "string" and not isinstance(value, str):
            raise DSHBridgeError(f"Argument {name} must be a string.")
        allowed = property_schema.get("enum")
        if allowed is not None and value not in allowed:
            raise DSHBridgeError(f"Argument {name} must be one of: {', '.join(allowed)}")


def _enforce_egress_boundary(result: dict[str, Any]) -> None:
    serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > MAX_RESULT_CHARACTERS:
        raise DSHBridgeError("Tool result exceeds the DSH bridge size limit.")
    if _ABSOLUTE_PATH.search(serialized):
        raise DSHBridgeError("Tool result contained an absolute path and was blocked.")
    if _RAW_RESEARCH_FILE.search(serialized):
        raise DSHBridgeError("Tool result contained a raw research filename and was blocked.")


def execute_dsh_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one audited SteelAI read-only tool for DSH."""
    definition = _definition(name)
    safe_arguments = {} if arguments is None else arguments
    _validate_arguments(definition, safe_arguments)
    result = execute_readonly_tool(name, safe_arguments)
    _enforce_egress_boundary(result)
    return result
