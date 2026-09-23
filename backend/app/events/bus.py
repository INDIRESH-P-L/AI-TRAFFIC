"""TRAFFICINTEL AI - Typed Event Bus

In-process publish/subscribe with per-subscriber topic filters and explicit
backpressure handling.

Three design decisions worth stating, because each trades something away:

1. **A slow subscriber is dropped, not buffered indefinitely.** Each subscriber
   owns a bounded queue. When it fills, the OLDEST event is discarded and the
   loss is counted and reported on the subscriber's stats. An unbounded queue
   would turn one stalled WebSocket into server memory growth; silently
   dropping without counting would let an operator believe they had seen
   everything. The console surfaces `dropped_events` so a gap is visible.

2. **Publishing never blocks and never raises into the caller.** A signal
   command must not fail because a notification subscriber threw. Handler
   errors are logged and counted against that subscriber.

3. **The topic vocabulary is closed.** Publishing an undeclared topic raises in
   development and is logged-and-dropped in production, because a typo in a
   topic name otherwise produces an event nobody receives and no error anybody
   notices.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.events import topics as topic_vocab

logger = logging.getLogger("trafficintel.events")

DEFAULT_QUEUE_SIZE = 256


@dataclass
class Event:
    """One thing that happened, with everything a subscriber needs to act."""

    topic: str
    payload: Dict[str, Any]
    timestamp: str
    sequence: int
    #: Correlates every event produced while handling one request.
    trace_id: Optional[str] = None

    def to_envelope(self) -> Dict[str, Any]:
        """Wire format. `event` is kept as the key for console compatibility."""
        return {
            "event": self.topic,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "trace_id": self.trace_id,
            "payload": self.payload,
        }


@dataclass
class Subscription:
    """One subscriber's view of the stream."""

    id: str
    patterns: List[str]
    queue: "asyncio.Queue[Event]" = field(default_factory=lambda: asyncio.Queue(maxsize=DEFAULT_QUEUE_SIZE))
    delivered: int = 0
    dropped: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def wants(self, topic: str) -> bool:
        return any(topic_vocab.matches(pattern, topic) for pattern in self.patterns)

    def stats(self) -> Dict[str, Any]:
        return {
            "subscription_id": self.id,
            "patterns": self.patterns,
            "delivered": self.delivered,
            "dropped_events": self.dropped,
            "queue_depth": self.queue.qsize(),
            "queue_capacity": self.queue.maxsize,
            "created_at": self.created_at,
        }


class EventBus:
    """Process-local event bus. One instance per API process."""

    def __init__(self) -> None:
        self._subscriptions: Dict[str, Subscription] = {}
        self._sequence = 0
        self._published_by_topic: Dict[str, int] = {}
        self._total_dropped = 0

    # -- subscription management ------------------------------------------

    def subscribe(
        self,
        subscription_id: str,
        patterns: Optional[List[str]] = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> Subscription:
        subscription = Subscription(
            id=subscription_id,
            patterns=patterns or ["*"],
            queue=asyncio.Queue(maxsize=queue_size),
        )
        self._subscriptions[subscription_id] = subscription
        logger.debug("Subscription %s registered for %s", subscription_id, subscription.patterns)
        return subscription

    def unsubscribe(self, subscription_id: str) -> None:
        self._subscriptions.pop(subscription_id, None)

    def update_patterns(self, subscription_id: str, patterns: List[str]) -> bool:
        subscription = self._subscriptions.get(subscription_id)
        if not subscription:
            return False
        subscription.patterns = patterns or ["*"]
        return True

    # -- publishing --------------------------------------------------------

    def publish(
        self,
        topic: str,
        payload: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> Optional[Event]:
        """Fan an event out to matching subscribers. Never blocks, never raises."""
        if not topic_vocab.is_valid_topic(topic):
            message = "Refusing to publish undeclared topic '{}'".format(topic)
            if settings.ENVIRONMENT.lower() != "production":
                raise ValueError(message + ". Declare it in app/events/topics.py.")
            logger.error(message)
            return None

        self._sequence += 1
        event = Event(
            topic=topic,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
            sequence=self._sequence,
            trace_id=trace_id,
        )
        self._published_by_topic[topic] = self._published_by_topic.get(topic, 0) + 1

        for subscription in list(self._subscriptions.values()):
            if not subscription.wants(topic):
                continue
            self._enqueue(subscription, event)

        return event

    def _enqueue(self, subscription: Subscription, event: Event) -> None:
        """Backpressure: drop the oldest event rather than grow without bound."""
        try:
            subscription.queue.put_nowait(event)
            subscription.delivered += 1
            return
        except asyncio.QueueFull:
            pass

        try:
            subscription.queue.get_nowait()          # discard oldest
            subscription.dropped += 1
            self._total_dropped += 1
            subscription.queue.put_nowait(event)
            subscription.delivered += 1
            logger.warning(
                "Subscriber %s is behind; dropped an event to make room (total dropped %d)",
                subscription.id, subscription.dropped,
            )
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            # Racing consumer emptied or refilled the queue; the event is lost
            # for this subscriber and the loss is counted.
            subscription.dropped += 1
            self._total_dropped += 1

    # -- introspection -----------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        return {
            "sequence": self._sequence,
            "subscribers": len(self._subscriptions),
            "total_dropped_events": self._total_dropped,
            "published_by_topic": dict(self._published_by_topic),
            "subscriptions": [s.stats() for s in self._subscriptions.values()],
        }

    def subscription(self, subscription_id: str) -> Optional[Subscription]:
        return self._subscriptions.get(subscription_id)

    def reset(self) -> None:
        """Test helper. Never called by application code."""
        self._subscriptions.clear()
        self._sequence = 0
        self._published_by_topic.clear()
        self._total_dropped = 0


event_bus = EventBus()
