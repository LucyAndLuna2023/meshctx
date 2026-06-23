"""
MeshCtx Plugin Template — Your Plugin Name Here
=================================================
Quick start:
  1. Copy this directory
  2. Edit manifest.json
  3. Implement your plugin class
  4. Submit to meshctx-plugins repo

Your plugin class must have:
  - __init__(self, config: dict)
  - on_start(self) -> None
  - on_stop(self) -> None
  - get_tools(self) -> List[dict]
"""


class MyPlugin:
    """Your MeshCtx plugin implementation."""

    def __init__(self, config: dict = None):
        self.config = config or {}

    def on_start(self):
        """Called when plugin is activated."""
        pass

    def on_stop(self):
        """Called when plugin is deactivated."""
        pass

    def get_tools(self):
        """Return list of tools this plugin provides."""
        return [
            {
                "name": "my_tool",
                "description": "What this tool does",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "Tool input"}
                    }
                },
                "handler": self.handle_my_tool
            }
        ]

    def handle_my_tool(self, input: str) -> str:
        """Tool implementation."""
        return f"Processed: {input}"
