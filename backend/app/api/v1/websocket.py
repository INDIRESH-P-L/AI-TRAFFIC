"""TRAFFICINTEL AI - Real-Time WebSocket Gateway

Each connected console gets its own bus subscription with its own topic filter
and its own bounded queue, so one stalled client cannot slow the others down
and cannot grow server memory without bound.

Clients may send:
    {"action": "subscribe",   "topics": ["signal.*", "incident.*"]}
    {"action": "unsubscribe"}                  -> falls back to no topics
    {"action": "stats"}                        -> this connection's counters
    "ping"                                     -> "pong"

The server sends event envelopes ({event, timestamp, sequence, trace_id,
payload}) plus a `stream.status` control frame on connect and whenever events
were dropped. A gap in the stream is reported to the client rather than hidden:
the console shows a dropped-event count so an operator knows their view may be
incomplete and can refresh.

Authentication: the gateway requires a valid bearer token, passed as the
`token` query parameter (browsers cannot set headers on a WebSocket handshake).
An unauthenticated socket is closed before any event reaches it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.database import SessionLocal
from app.core.security import decode_token
from app.events import topics as topic_vocab
from app.events.bus import Event, Subscription, event_bus

logger = logging.getLogger("trafficintel.websocket")

DEFAULT_TOPICS = ["*"]


def _authenticate(token: Optional[str]) -> Optional[str]:
    """Returns the username for a valid token, or None."""
    if not token:
        return None
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001 - any failure is simply "not authenticated"
        return None

    username = payload.get("sub")
    if not username:
        return None

    from app.models.entities import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        return username if user and user.is_active else None
    finally:
        db.close()


class ConnectionManager:
    """Tracks live console connections and their bus subscriptions."""

    def __init__(self) -> None:
        self._connections: Dict[str, Dict[str, Any]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        username: str,
        patterns: Optional[List[str]] = None,
    ) -> str:
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        subscription = event_bus.subscribe(connection_id, patterns or DEFAULT_TOPICS)
        self._connections[connection_id] = {
            "websocket": websocket,
            "username": username,
            "subscription": subscription,
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "reported_drops": 0,
        }
        logger.info("Console %s connected (%s) on %s", connection_id, username, subscription.patterns)
        return connection_id

    def disconnect(self, connection_id: str) -> None:
        event_bus.unsubscribe(connection_id)
        self._connections.pop(connection_id, None)

    def subscription(self, connection_id: str) -> Optional[Subscription]:
        entry = self._connections.get(connection_id)
        return entry["subscription"] if entry else None

    def stats(self) -> Dict[str, Any]:
        return {
            "connections": len(self._connections),
            "clients": [
                {
                    "connection_id": cid,
                    "username": entry["username"],
                    "connected_at": entry["connected_at"],
                    **entry["subscription"].stats(),
                }
                for cid, entry in self._connections.items()
            ],
        }

    async def broadcast_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Compatibility shim for callers that predate the bus.

        Translates a legacy topic name to the current vocabulary and publishes
        it. Kept so existing endpoints keep emitting while they are migrated.
        """
        topic = topic_vocab.LEGACY_ALIASES.get(event_type, event_type)
        if not topic_vocab.is_valid_topic(topic):
            logger.warning("Dropping legacy broadcast of unknown topic '%s'", event_type)
            return
        event_bus.publish(topic, payload)


ws_manager = ConnectionManager()


async def _send(websocket: WebSocket, message: Dict[str, Any]) -> bool:
    if websocket.client_state != WebSocketState.CONNECTED:
        return False
    try:
        await websocket.send_json(message)
        return True
    except Exception:  # noqa: BLE001 - the pump treats any failure as a close
        return False


async def _pump_events(websocket: WebSocket, connection_id: str) -> None:
    """Drains this connection's queue onto the socket until it closes."""
    subscription = ws_manager.subscription(connection_id)
    if subscription is None:
        return

    entry = ws_manager._connections.get(connection_id)  # noqa: SLF001 - same module

    while True:
        event: Event = await subscription.queue.get()
        if not await _send(websocket, event.to_envelope()):
            return

        # Tell the client when it has fallen behind, so a gap in its view is
        # visible rather than silent.
        if entry and subscription.dropped > entry["reported_drops"]:
            entry["reported_drops"] = subscription.dropped
            await _send(websocket, {
                "event": "stream.status",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "status": "EVENTS_DROPPED",
                    "dropped_events": subscription.dropped,
                    "detail": (
                        "This connection fell behind and events were discarded. "
                        "The view may be incomplete; refresh to resynchronise."
                    ),
                },
            })


async def _handle_client_message(
    websocket: WebSocket, connection_id: str, raw: str
) -> None:
    if raw == "ping":
        await websocket.send_text("pong")
        return

    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return

    action = message.get("action")

    if action == "subscribe":
        requested = message.get("topics") or DEFAULT_TOPICS
        # Validate each pattern so a client cannot silently subscribe to
        # nothing because of a typo.
        invalid = [
            pattern for pattern in requested
            if pattern != "*"
            and not pattern.endswith(".*")
            and not topic_vocab.is_valid_topic(pattern)
        ]
        if invalid:
            await _send(websocket, {
                "event": "stream.status",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"status": "INVALID_TOPICS", "topics": invalid},
            })
            return

        event_bus.update_patterns(connection_id, requested)
        await _send(websocket, {
            "event": "stream.status",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"status": "SUBSCRIBED", "topics": requested},
        })

    elif action == "unsubscribe":
        event_bus.update_patterns(connection_id, [])
        await _send(websocket, {
            "event": "stream.status",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"status": "UNSUBSCRIBED", "topics": []},
        })

    elif action == "stats":
        subscription = ws_manager.subscription(connection_id)
        await _send(websocket, {
            "event": "stream.status",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"status": "STATS", **(subscription.stats() if subscription else {})},
        })


async def websocket_gateway(websocket: WebSocket, token: Optional[str] = None) -> None:
    """Entry point mounted at /api/v1/ws."""
    username = _authenticate(token)
    if not username:
        # 1008 = policy violation. Closed before accept so no event is ever
        # delivered to an unauthenticated socket.
        await websocket.close(code=1008, reason="Authentication required")
        return

    connection_id = await ws_manager.connect(websocket, username)

    await _send(websocket, {
        "event": "stream.status",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "status": "CONNECTED",
            "connection_id": connection_id,
            "topics": DEFAULT_TOPICS,
            "detail": (
                "Subscribed to all topics. An open socket does not imply data is "
                "flowing: a quiet network produces no events."
            ),
        },
    })

    pump = asyncio.create_task(_pump_events(websocket, connection_id))
    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_client_message(websocket, connection_id, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("Console %s closed: %s", connection_id, exc)
    finally:
        pump.cancel()
        ws_manager.disconnect(connection_id)
