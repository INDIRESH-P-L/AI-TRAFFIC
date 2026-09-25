"""TRAFFICINTEL AI - Transit Signal Priority (TSP) Endpoints

Conditional TSP from GTFS-Realtime. Never fabricates buses or arrival times: with
no feed configured the platform says TRANSIT_FEED_NOT_CONFIGURED.

* `POST /transit/tsp/evaluate`       - fetch the configured feeds and evaluate.
* `POST /transit/tsp/evaluate-feed`  - evaluate feed bytes pushed by a gateway
                                       (base64 protobuf), e.g. from a depot or
                                       on-board unit.

Both default to a dry run, which needs only `telemetry:read` and writes nothing.
Dispatching green extensions (`dry_run=false`) needs `signal:command`, and goes
through the Safety Engine and the single command dispatcher.
"""

import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_scope
from app.governance import scopes as scope_vocab
from app.models.entities import TransitEvent, User
from app.providers.gtfs_rt import GtfsRtDecodeError, decode_feed
from app.providers.transit_provider import GtfsRealtimeProvider
from app.transit.tsp import TransitSignalPriority

router = APIRouter(prefix="/transit", tags=["Transit Priority"])


@router.get("")
def list_transit_events(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    events = db.query(TransitEvent).order_by(TransitEvent.timestamp.desc()).limit(200).all()
    configured = GtfsRealtimeProvider().configured
    if configured:
        status_label = "TRANSIT_FEED_CONFIGURED"
        message = (
            "A GTFS-Realtime feed is configured. {} priority evaluation(s) are on record; "
            "see provider health for whether the feed is currently answering.".format(len(events))
        )
    else:
        status_label = "TRANSIT_FEED_NOT_CONFIGURED"
        message = "No GTFS-Realtime feed is configured, so no transit vehicle is being tracked."
    return {
        "status": status_label,
        "feed_configured": configured,
        "message": message,
        "evaluations_on_record": len(events),
        "events": events,
    }


def _ensure_dispatch_allowed(principal, dry_run: bool) -> None:
    if not dry_run and not principal.has(scope_vocab.COMMAND_SIGNAL):
        raise HTTPException(status_code=403, detail=(
            "Dispatching transit priority changes signal timing and requires the "
            "'signal:command' scope. A dry run needs only 'telemetry:read'."
        ))


def _actor_id(principal) -> Optional[str]:
    return getattr(getattr(principal, "user", None), "id", None)


@router.post("/tsp/evaluate")
def evaluate_configured_feed(
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
    principal=Depends(require_scope(scope_vocab.READ_TELEMETRY)),
):
    _ensure_dispatch_allowed(principal, dry_run)
    provider = GtfsRealtimeProvider()
    if not provider.configured:
        return {
            "status": "TRANSIT_FEED_NOT_CONFIGURED",
            "detail": (
                "Set GTFS_RT_VEHICLE_POSITIONS_URL (and GTFS_RT_TRIP_UPDATES_URL for "
                "schedule adherence) to an agency's GTFS-Realtime feed. The platform does "
                "not simulate buses."
            ),
            "decisions": [],
        }

    ok, message, vehicles_bytes = provider.fetch_vehicle_positions()
    if not ok:
        return {"status": "FEED_UNAVAILABLE", "detail": message, "decisions": []}
    trip_updates = []
    trip_status = "NOT_CONFIGURED"
    if provider.trip_updates_url:
        ok_tu, message_tu, updates_bytes = provider.fetch_trip_updates()
        trip_status = "FETCHED" if ok_tu else "UNAVAILABLE: {}".format(message_tu)
        if ok_tu:
            try:
                trip_updates = decode_feed(updates_bytes)["trip_updates"]
            except GtfsRtDecodeError as exc:
                trip_status = "UNDECODABLE: {}".format(exc)
    try:
        feed = decode_feed(vehicles_bytes)
    except GtfsRtDecodeError as exc:
        return {"status": "FEED_UNDECODABLE", "detail": str(exc), "decisions": []}

    result = TransitSignalPriority.evaluate(db, feed, trip_updates, dry_run,
                                            _actor_id(principal), principal.identity)
    result["trip_updates_feed"] = trip_status
    return result


class PushedFeed(BaseModel):
    vehicle_positions_b64: str
    trip_updates_b64: Optional[str] = None


@router.post("/tsp/evaluate-feed")
def evaluate_pushed_feed(
    body: PushedFeed,
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
    principal=Depends(require_scope(scope_vocab.READ_TELEMETRY)),
):
    _ensure_dispatch_allowed(principal, dry_run)
    try:
        feed = decode_feed(base64.b64decode(body.vehicle_positions_b64, validate=True))
        trip_updates = (
            decode_feed(base64.b64decode(body.trip_updates_b64, validate=True))["trip_updates"]
            if body.trip_updates_b64 else feed.get("trip_updates", [])
        )
    except (GtfsRtDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Feed could not be decoded: {}".format(exc))
    return TransitSignalPriority.evaluate(db, feed, trip_updates, dry_run,
                                          _actor_id(principal), principal.identity)
