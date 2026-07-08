"""meshctx ACP Server — real implementation (v3.115.16)"""
import json, logging
logger = logging.getLogger("meshctx.acp")

class ACPServer:
    """Agent Communication Protocol server."""
    def __init__(self):
        self.agents = {}
        self._handlers = {}
    
    def register_agent(self, agent_id: str, capabilities: list):
        self.agents[agent_id] = {"id": agent_id, "capabilities": capabilities, "status": "ready"}
    
    def on(self, event: str, handler):
        self._handlers[event] = handler
    
    async def handle_message(self, message: dict) -> dict:
        event = message.get("event", "message")
        handler = self._handlers.get(event)
        if handler:
            return await handler(message)
        return {"status": "unhandled", "event": event}
    
    def list_agents(self) -> list:
        return list(self.agents.values())
    
    def stats(self) -> dict:
        return {"agents": len(self.agents), "handlers": len(self._handlers)}
