from __future__ import annotations

import argparse
import json
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from steelai.dsh_bridge import bridge_status, execute_dsh_tool


mcp = FastMCP(
    "SteelAI Read-Only Research",
    instructions=(
        "Use these tools only for structured, evidence-bounded wear-resistant-steel "
        "research. Never describe model estimates as experimental truth, never infer "
        "causation from correlation, and never request raw files or local paths."
    ),
)


@mcp.tool()
def get_bridge_status() -> dict[str, Any]:
    """Show the SteelAI-DSH bridge policy without reading research data."""
    return bridge_status()


@mcp.tool()
def list_samples() -> dict[str, Any]:
    """List processed sample IDs and table completeness; never return raw files."""
    return execute_dsh_tool("list_samples")


@mcp.tool()
def get_sample_bundle(sample_id: str) -> dict[str, Any]:
    """Read the structured, sanitized evidence bundle for one exact sample ID."""
    return execute_dsh_tool("get_sample_bundle", {"sample_id": sample_id})


@mcp.tool()
def compare_samples(control_id: str, comparison_id: str) -> dict[str, Any]:
    """Build a deterministic comparison with facts, hypotheses and limits separated."""
    return execute_dsh_tool(
        "compare_samples",
        {"control_id": control_id, "comparison_id": comparison_id},
    )


@mcp.tool()
def calculate_physics_card(sample_id: str) -> dict[str, Any]:
    """Calculate empirical physics estimates; outputs are not experimental truth."""
    return execute_dsh_tool("calculate_physics_card", {"sample_id": sample_id})


@mcp.tool()
def get_ebsd_summary(
    scale: Literal["low_resolution", "high_resolution"],
) -> dict[str, Any]:
    """Read an existing EBSD comparison while keeping acquisition scales separate."""
    return execute_dsh_tool("get_ebsd_summary", {"scale": scale})


@mcp.tool()
def get_autodimple_summary() -> dict[str, Any]:
    """Read the existing sanitized AutoDimple summary without running segmentation."""
    return execute_dsh_tool("get_autodimple_summary")


@mcp.tool()
def get_evidence_validation_summary() -> dict[str, Any]:
    """Read deterministic claim gates and allowed/prohibited scientific wording."""
    return execute_dsh_tool("get_evidence_validation_summary")


def main() -> None:
    parser = argparse.ArgumentParser(description="SteelAI read-only MCP server for DSH")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Print a path-free bridge status payload and exit.",
    )
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(bridge_status(), ensure_ascii=False, indent=2))
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
