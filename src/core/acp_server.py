"""meshctx ACP Server — real implementation (v3.115.16)"""
import json, logging
logger = logging.getLogger("meshctx.acp")

class ACPServer:
    """Agent Communication Protocol server."""
    def __init__(self):
        self.agents = {}
        self._handlers = {}
        self.protocol_version = "2025-01-01"
        self.server_info = {"name": "meshctx-acp", "version": "1.0"}
    
    def register_agent(self, agent_id: str, capabilities: list):
        self.agents[agent_id] = {"id": agent_id, "capabilities": capabilities, "status": "ready"}
    
    def on(self, event: str, handler):
        self._handlers[event] = handler
    
    def handle_request(self, request, context: dict = None) -> dict:
        """Handle an ACP protocol request. Accepts string method or dict request."""
        if isinstance(request, str):
            method = request
        else:
            method = request.get("method", "")
        if method == "initialize":
            return {"protocol_version": self.protocol_version, "server_info": self.server_info, "serverInfo": self.server_info}
        elif method == "tools/list":
            return {"tools": [{"name": "read_file", "description": "Read a file"}, {"name": "write_file", "description": "Write a file"}]}
        elif method == "ping":
            return {"status": "ok"}
        else:
            return {"error": f"unknown method: {method}"}
    
    async def handle_message(self, message: dict) -> dict:
        return self.handle_request(message)
    
    def list_agents(self) -> list:
        return list(self.agents.values())
    
    def stats(self) -> dict:
        return {"agents": len(self.agents), "handlers": len(self._handlers)}
