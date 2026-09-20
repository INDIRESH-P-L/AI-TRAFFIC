"""TRAFFICINTEL AI - Grounded LLM Copilot Service

Operations assistant for traffic engineers and control-room operators.
Strict grounding: operates purely over actual database state and indexed documentation.
Rule #66 & #108: If telemetry is unavailable, honestly states that no live telemetry exists.
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models.entities import (
    Intersection, SignalController, TrafficMetric, Incident, Device, Alert
)
from app.copilot.knowledge_rag import KnowledgeRAGEngine
from app.schemas.domain import CopilotResponse


class GroundedCopilotService:
    """Executes strictly grounded queries for the operator."""

    @classmethod
    def get_intersection_state(cls, db: Session, intersection_id: str) -> Optional[Dict[str, Any]]:
        inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
        if not inter:
            return None
        return {
            "id": inter.id,
            "name": inter.name,
            "code": inter.code,
            "status": inter.operational_status,
            "jurisdiction": inter.jurisdiction
        }

    @classmethod
    def get_live_traffic(cls, db: Session, intersection_id: str) -> Optional[Dict[str, Any]]:
        metric = db.query(TrafficMetric).filter(
            TrafficMetric.intersection_id == intersection_id
        ).order_by(TrafficMetric.timestamp.desc()).first()

        if not metric or metric.data_quality == "NO_DATA" or metric.vehicle_count is None:
            return None

        return {
            "vehicle_count": metric.vehicle_count,
            "avg_speed_kph": metric.avg_speed_kph,
            "occupancy_pct": metric.occupancy_pct,
            "queue_length_meters": metric.queue_length_meters,
            "traffic_pressure": metric.traffic_pressure,
            "quality": metric.data_quality,
            "timestamp": metric.timestamp.isoformat() if metric.timestamp else None,
            "calculation_method": metric.calculation_method
        }

    @classmethod
    def get_signal_state(cls, db: Session, intersection_id: str) -> Dict[str, Any]:
        controllers = db.query(SignalController).filter(SignalController.intersection_id == intersection_id).all()
        if not controllers:
            return {"status": "NO_CONTROLLER_CONFIGURED", "controllers": []}

        res = []
        for c in controllers:
            res.append({
                "id": c.id,
                "name": c.name,
                "vendor": c.vendor,
                "model": c.model,
                "connection_status": c.connection_status,
                "active_phase": c.active_phase,
                "control_mode": c.control_mode
            })
        return {"status": "CONFIGURED", "controllers": res}

    @classmethod
    def get_active_incidents(cls, db: Session, intersection_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = db.query(Incident).filter(Incident.status.in_(["DETECTED", "SUSPECTED", "VERIFIED", "ACTIVE"]))
        if intersection_id:
            q = q.filter(Incident.intersection_id == intersection_id)
        incidents = q.all()
        return [
            {
                "id": inc.id,
                "title": inc.title,
                "type": inc.type,
                "severity": inc.severity,
                "status": inc.status,
                "detected_at": inc.detected_at.isoformat() if inc.detected_at else None,
                "source": inc.source
            } for inc in incidents
        ]

    @classmethod
    def answer_query(cls, db: Session, query: str, intersection_id: Optional[str] = None) -> CopilotResponse:
        """Processes user operational query using real tool execution."""
        grounding_data_used = []
        citations = []
        suggested_actions = []

        # 1. Resolve Intersection Context
        target_intersection = None
        if intersection_id:
            target_intersection = db.query(Intersection).filter(Intersection.id == intersection_id).first()
        else:
            # Check if an intersection code or name is mentioned in the query
            intersections = db.query(Intersection).all()
            for inter in intersections:
                if inter.name.lower() in query.lower() or inter.code.lower() in query.lower():
                    target_intersection = inter
                    break

        # 2. Check for RAG Documentation queries
        doc_keywords = ["timing", "mutcd", "yellow", "nema", "clearance", "minimum green", "sop", "preemption", "standard"]
        matched_docs = []
        if any(k in query.lower() for k in doc_keywords):
            matched_docs = KnowledgeRAGEngine.search_operational_documentation(db, query)
            for d in matched_docs:
                grounding_data_used.append(f"Standard Document: {d['document_title']}")
                citations.append({
                    "title": d["document_title"],
                    "category": d["category"],
                    "snippet": d["content"][:200] + "..."
                })

        # 3. Formulate Truthful Grounded Response
        if target_intersection:
            grounding_data_used.append(f"Intersection Record: {target_intersection.name} ({target_intersection.code})")
            live_traffic = cls.get_live_traffic(db, target_intersection.id)
            signal_state = cls.get_signal_state(db, target_intersection.id)
            active_incidents = cls.get_active_incidents(db, target_intersection.id)

            if live_traffic is None:
                telemetry_state = "NO_LIVE_TELEMETRY"
                answer = (
                    f"There is currently no live traffic telemetry available for {target_intersection.name} "
                    f"({target_intersection.code}), so I cannot determine traffic conditions or causes from system data.\n\n"
                    f"Infrastructure Status:\n"
                    f"• Operational Status: {target_intersection.operational_status}\n"
                    f"• Signal Controllers: {len(signal_state.get('controllers', []))} configured "
                    f"({signal_state.get('controllers', [{}])[0].get('connection_status', 'NOT_CONNECTED') if signal_state.get('controllers') else 'None'})\n"
                    f"• Active Incidents: {len(active_incidents)}"
                )
                suggested_actions.append({
                    "action": "CONNECT_DATA_SOURCE",
                    "description": f"Verify camera/sensor telemetry connection for {target_intersection.name}"
                })
            else:
                telemetry_state = "REAL_TELEMETRY_AVAILABLE"
                grounding_data_used.append(f"Live Traffic Metric: {live_traffic['vehicle_count']} veh, Speed: {live_traffic['avg_speed_kph']} km/h")
                answer = (
                    f"Current measured traffic state for {target_intersection.name}:\n"
                    f"• Vehicle Count: {live_traffic['vehicle_count']} vehicles\n"
                    f"• Average Speed: {live_traffic['avg_speed_kph']} km/h\n"
                    f"• Approach Occupancy: {live_traffic['occupancy_pct']}%\n"
                    f"• Queue Length: {live_traffic['queue_length_meters']} meters\n"
                    f"• Telemetry Freshness: {live_traffic['quality']} (Source calculation: {live_traffic['calculation_method']})"
                )
                if active_incidents:
                    answer += f"\n\nActive Incidents ({len(active_incidents)}):\n"
                    for inc in active_incidents:
                        answer += f"• [{inc['severity']}] {inc['title']} (Status: {inc['status']})\n"

        elif matched_docs:
            telemetry_state = "DOCUMENTATION_RETRIEVED"
            answer = f"According to traffic engineering operational standards:\n\n{matched_docs[0]['content']}"

        else:
            # General system status query
            total_intersections = db.query(Intersection).count()
            total_incidents = db.query(Incident).filter(Incident.status != "RESOLVED").count()
            total_devices = db.query(Device).count()

            telemetry_state = "SYSTEM_SUMMARY"
            grounding_data_used.append("Global System Registry")

            answer = (
                f"TRAFFICINTEL AI Central Platform Status:\n"
                f"• Configured Intersections: {total_intersections}\n"
                f"• Active Tracked Incidents: {total_incidents}\n"
                f"• Configured Roadside Devices: {total_devices}\n\n"
                f"To inspect conditions or run diagnostics, specify an intersection name or connect live telemetry streams."
            )

        return CopilotResponse(
            query=query,
            answer=answer,
            grounding_data_used=grounding_data_used,
            telemetry_state=telemetry_state,
            citations=citations,
            suggested_actions=suggested_actions
        )
