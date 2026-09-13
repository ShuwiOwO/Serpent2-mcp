"""Compatibility layer for the MCP Python SDK v1 (FastMCP) and v2 (MCPServer)."""

from __future__ import annotations

try:  # MCP SDK >= 2.0
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:  # pragma: no cover - MCP SDK 1.x
    from mcp.server.fastmcp import FastMCP as Server  # type: ignore[assignment]

__all__ = ["Server"]
