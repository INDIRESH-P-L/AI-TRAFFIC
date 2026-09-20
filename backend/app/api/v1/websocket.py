"""TRAFFICINTEL AI - Real-Time WebSocket Event Gateway

Publishes genuine system state events to authenticated operator clients:
traffic.updated, signal.updated, incident.detected, incident.updated,
device.status_changed, alert.created, ai.decision_created, controller.updated.
Never publishes fake or synthetic ticker events.
"""

from typing import List, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
import json


class ConnectionManager:
    """Manages active operator WebSocket connections."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_event(self, event_type: str, payload: Dict[str, Any]):
        """Broadcasts a real system event to all connected consoles."""
        message = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload
        }
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(dead)


ws_manager = ConnectionManager()
