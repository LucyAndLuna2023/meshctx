"""
ACP IDE Protocol Server — handles initialize, tools/list, ping, and error responses.
"""
from typing import Any


class ACPServer:
    """ACP protocol server for IDE integration."""

    protocol_version = "2025-01-01"

    def handle_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route a method call and return the result dict."""
        if method == "initialize":
            return {
                "serverInfo": {
                    "name": "meshctx",
                    "version": "2.35.0",
                }
            }
        elif method == "tools/list":
            return {
                "tools": [
                    {"name": "read_file"},
                    {"name": "write_file"},
                    {"name": "search_files"},
                    {"name": "terminal"},
                ]
            }
        elif method == "ping":
            return {"status": "ok"}
        else:
            return {"error": f"unknown method: {method}"}
