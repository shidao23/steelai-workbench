"""Stdio MCP adapter for the five T61 governed research tools."""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from steelai.research_protocol import GovernedResearchToolLayer, protocol_status


mcp = FastMCP(
    "SteelAI Governed Research Tools",
    instructions=(
        "Local tested SteelAI MCP subset. Every call requires a versioned A2A task "
        "envelope. Outputs are nonformal candidates and require human review."
    ),
)
_layer = GovernedResearchToolLayer()


@mcp.tool()
def get_protocol_status() -> dict[str, Any]:
    """Return the tested local protocol scope and explicit limitations."""
    return protocol_status()


@mcp.tool()
def query_samples(request: dict[str, Any]) -> dict[str, Any]:
    """List the governed sample registry through a versioned task request."""
    return _layer.execute("query_samples", request)


@mcp.tool()
def get_verified_evidence(request: dict[str, Any]) -> dict[str, Any]:
    """Return a digest summary for one verified sample evidence bundle."""
    return _layer.execute("get_verified_evidence", request)


@mcp.tool()
def run_descriptive_statistics(request: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic descriptive statistics as a nonformal candidate."""
    return _layer.execute("run_descriptive_statistics", request)


@mcp.tool()
def run_physics_calculation(request: dict[str, Any]) -> dict[str, Any]:
    """Run a registered empirical Physics Card as a nonmeasurement candidate."""
    return _layer.execute("run_physics_calculation", request)


@mcp.tool()
def generate_report_candidate(request: dict[str, Any]) -> dict[str, Any]:
    """Build a source-call-bound report candidate that still requires human review."""
    return _layer.execute("generate_report_candidate", request)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SteelAI governed research MCP stdio server")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(protocol_status(), ensure_ascii=False, indent=2))
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
