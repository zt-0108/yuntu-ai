from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlparse


_MAX_TOOL_RESPONSE_CHARS = 2_000_000


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("RAIL_MCP_URL must be an absolute HTTP(S) URL")


def _decode_tool_result(result: Any) -> dict[str, Any]:
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        raise RuntimeError("rail MCP tool returned an error")

    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured

    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        if len(text) > _MAX_TOOL_RESPONSE_CHARS:
            raise RuntimeError("rail MCP response is too large")
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError("rail MCP returned no JSON object")


def _resolve_tool_name(available: set[str], *aliases: str) -> str:
    for alias in aliases:
        if alias in available:
            return alias
    raise RuntimeError(f"rail MCP is missing required tool: {aliases[0]}")


async def query_rail_routes(
    *,
    url: str,
    timeout_seconds: float,
    routes: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Call the query-only rail tools once per route using one MCP session."""
    _validate_url(url)

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:  # pragma: no cover - depends on optional runtime install
        raise RuntimeError("mcp package is not installed") from exc

    async with asyncio.timeout(timeout_seconds):
        async with streamable_http_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                available = {tool.name for tool in listed.tools}
                ticket_tool = _resolve_tool_name(
                    available,
                    "query-tickets",
                    "query_tickets",
                )
                price_tool = _resolve_tool_name(
                    available,
                    "query-ticket-price",
                    "query_ticket_price",
                )

                responses: list[dict[str, Any]] = []
                for route in routes:
                    arguments = {
                        "from_station": route["from_station"],
                        "to_station": route["to_station"],
                        "train_date": route["train_date"],
                    }
                    tickets = _decode_tool_result(
                        await session.call_tool(ticket_tool, arguments=arguments)
                    )
                    try:
                        prices = _decode_tool_result(
                            await session.call_tool(price_tool, arguments=arguments)
                        )
                    except Exception:
                        # Ticket availability remains useful when the optional
                        # fare lookup is temporarily unavailable.
                        prices = {}
                    responses.append({"tickets": tickets, "prices": prices})
                return responses
