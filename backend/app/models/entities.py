"""TRAFFICINTEL AI - Database Entities & Schema

Comprehensive relational domain models representing physical ITS infrastructure,
real hardware controllers, genuine telemetry streams, deterministic safety audits,
and zero fake operational data.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, JSON, Enum
)
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid


def utc_now():
    return datetime.now(timezone.utc)


def generate_uuid():
    return str(uuid.uuid4())


# ==========================================
# 1. Identity, Roles & Auditing
# ==========================================

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(128), nullable=False)
    role = Column(String(32), default="OPERATOR", nullable=False)  # ADMIN, ENGINEER, OPERATOR, AUDITOR
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    last_login = Column(DateTime, nullable=True)

    audit_logs = relationship("AuditLog", back_populates="user")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    actor_username = Column(String(64), nullable=False)
    action = Column(String(64), nullable=False, index=True)  # e.g., SIGNAL_COMMAND_SENT, INCIDENT_VERIFIED
    resource_type = Column(String(64), nullable=False)       # e.g., SignalController, Intersection
    resource_id = Column(String(64), nullable=True)
    result = Column(String(32), nullable=False)             # EXECUTED, REJECTED, FAILED, CANCELLED
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    request_id = Column(String(64), nullable=True)
    timestamp = Column(DateTime, default=utc_now, index=True)

    # --- Tamper-evident hash chain --------------------------------------
    # entry_hash = SHA256(sequence || previous_hash || canonical_json(entry)).
    # Altering or deleting a historical row breaks the chain from that point
    # on, and /audit/verify reports which sequence number broke.
    sequence = Column(Integer, nullable=True, unique=True, index=True)
    previous_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=True, index=True)

    user = relationship("User", back_populates="audit_logs")


# ==========================================
# 2. Infrastructure: Intersections & Geometry
# ==========================================

class Intersection(Base):
    __tablename__ = "intersections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(128), nullable=False, unique=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    jurisdiction = Column(String(64), default="Municipal DOT")
    operational_status = Column(String(32), default="DISCONNECTED")  # HEALTHY, DEGRADED, LIMITED, OFFLINE, MAINTENANCE
    corridor_id = Column(String(36), ForeignKey("corridors.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    corridor = relationship("Corridor", back_populates="intersections")
    approaches = relationship("Approach", back_populates="intersection", cascade="all, delete-orphan")
    controllers = relationship("SignalController", back_populates="intersection")
    cameras = relationship("Camera", back_populates="intersection")
    sensors = relationship("Sensor", back_populates="intersection")
    traffic_metrics = relationship("TrafficMetric", back_populates="intersection")
    incidents = relationship("Incident", back_populates="intersection")


class Corridor(Base):
    __tablename__ = "corridors"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    coordination_mode = Column(String(32), default="UNCOORDINATED")  # UNCOORDINATED, GREEN_WAVE, ADAPTIVE_COORDINATION
    cycle_length_sec = Column(Integer, default=90)
    created_at = Column(DateTime, default=utc_now)

    intersections = relationship("Intersection", back_populates="corridor")


class Approach(Base):
    __tablename__ = "approaches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), ForeignKey("intersections.id"), nullable=False)
    direction = Column(String(16), nullable=False)  # NORTHBOUND, SOUTHBOUND, EASTBOUND, WESTBOUND
    road_name = Column(String(128), nullable=False)
    speed_limit_kph = Column(Integer, default=50)

    intersection = relationship("Intersection", back_populates="approaches")
    lanes = relationship("Lane", back_populates="approach", cascade="all, delete-orphan")


class Lane(Base):
    __tablename__ = "lanes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    approach_id = Column(String(36), ForeignKey("approaches.id"), nullable=False)
    lane_number = Column(Integer, nullable=False)
    movement_type = Column(String(32), nullable=False)  # THRU, LEFT_TURN, RIGHT_TURN, THRU_RIGHT
    assigned_phase = Column(Integer, nullable=True)

    approach = relationship("Approach", back_populates="lanes")


# ==========================================
# 3. Signal Hardware & Phase Control
# ==========================================

class SignalController(Base):
    __tablename__ = "signal_controllers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), ForeignKey("intersections.id"), nullable=False)
    name = Column(String(128), nullable=False)
    vendor = Column(String(64), nullable=False)      # e.g., Econolite, Naztec, Siemens, Generic
    model = Column(String(64), nullable=False)       # e.g., ASC/3, Cobalt, m-Series
    protocol = Column(String(32), nullable=False)    # NTCIP_1202, ASC3_ETHERNET, REST_GATEWAY, TEST_SOCKET
    ip_address = Column(String(64), nullable=False)
    port = Column(Integer, default=501)
    connection_status = Column(String(32), default="NOT_CONNECTED")  # NOT_CONNECTED, CONNECTED, DISCONNECTED, ERROR
    control_mode = Column(String(32), default="LOCAL_COORDINATED")    # LOCAL_COORDINATED, ADAPTIVE_REMOTE, MANUAL_HOLD, FLASH
    active_phase = Column(Integer, nullable=True)
    current_phase_start = Column(DateTime, nullable=True)
    # Phases observed in yellow change or all-red clearance at the last read.
    # No phase displays green during clearance, so active_phase is null then -
    # without this, a conflicting movement would pass the conflict check while
    # the opposing approach is still clearing the intersection.
    clearing_phases = Column(JSON, nullable=True)
    cycle_length = Column(Integer, default=90)
    last_heartbeat = Column(DateTime, nullable=True)
    fallback_mode = Column(String(64), default="CONFIGURED_LOCAL_PLAN")

    intersection = relationship("Intersection", back_populates="controllers")
    phases = relationship("SignalPhase", back_populates="controller", cascade="all, delete-orphan")
    commands = relationship("SignalCommand", back_populates="controller")


class SignalPhase(Base):
    __tablename__ = "signal_phases"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    controller_id = Column(String(36), ForeignKey("signal_controllers.id"), nullable=False)
    phase_number = Column(Integer, nullable=False)
    ring = Column(Integer, default=1)               # Ring 1 or Ring 2 (NEMA Dual-Ring)
    barrier = Column(Integer, default=1)            # Barrier 1 or Barrier 2
    name = Column(String(64), nullable=False)       # e.g., EB Left, WB Thru
    min_green = Column(Integer, default=7)
    max_green = Column(Integer, default=65)
    yellow_change = Column(Integer, default=4)
    red_clearance = Column(Integer, default=2)
    ped_walk = Column(Integer, default=7)
    ped_clearance = Column(Integer, default=15)
    conflicting_phases = Column(JSON, default=list)  # List of phase numbers that cannot be concurrent

    controller = relationship("SignalController", back_populates="phases")


class SignalCommand(Base):
    __tablename__ = "signal_commands"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    idempotency_key = Column(String(64), unique=True, nullable=False)
    controller_id = Column(String(36), ForeignKey("signal_controllers.id"), nullable=False)
    requested_phase = Column(Integer, nullable=False)
    command_type = Column(String(32), default="PHASE_HOLD")  # PHASE_HOLD, FORCE_OFF, CALL, PREEMPTION
    duration_sec = Column(Integer, default=15)
    
    # Safety verification pipeline result
    safety_check_passed = Column(Boolean, default=False)
    safety_report = Column(JSON, nullable=True)
    
    status = Column(String(32), default="PENDING")  # PENDING, EXECUTED, REJECTED, FAILED, TIMED_OUT, CANCELLED
    operator_id = Column(String(36), nullable=True)
    issued_at = Column(DateTime, default=utc_now)
    expires_at = Column(DateTime, nullable=False)
    controller_acknowledged_at = Column(DateTime, nullable=True)
    response_payload = Column(JSON, nullable=True)

    controller = relationship("SignalController", back_populates="commands")


# ==========================================
# 4. Physical Devices: Cameras & Sensors
# ==========================================

class Device(Base):
    __tablename__ = "devices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_type = Column(String(32), nullable=False)  # CAMERA, RADAR, LOOP, CONTROLLER, WEATHER_STATION
    name = Column(String(128), nullable=False)
    status = Column(String(32), default="NOT_CONFIGURED")  # ONLINE, OFFLINE, DEGRADED, NOT_CONFIGURED
    ip_address = Column(String(64), nullable=True)
    port = Column(Integer, nullable=True)
    mac_address = Column(String(32), nullable=True)
    firmware_version = Column(String(64), nullable=True)
    last_seen = Column(DateTime, nullable=True)
    health_metrics = Column(JSON, nullable=True)
    config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), ForeignKey("intersections.id"), nullable=False)
    name = Column(String(128), nullable=False)
    stream_url = Column(String(255), nullable=False)  # RTSP or HTTP stream URL
    stream_status = Column(String(32), default="OFFLINE")  # CONNECTED, OFFLINE, STALE, ERROR
    resolution = Column(String(32), default="1920x1080")
    fps = Column(Float, default=0.0)
    detection_enabled = Column(Boolean, default=False)
    last_frame_timestamp = Column(DateTime, nullable=True)
    calibration_config = Column(JSON, nullable=True)

    intersection = relationship("Intersection", back_populates="cameras")
    detections = relationship("VehicleDetection", back_populates="camera")


class Sensor(Base):
    __tablename__ = "sensors"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), ForeignKey("intersections.id"), nullable=False)
    lane_id = Column(String(36), nullable=True)
    sensor_type = Column(String(32), nullable=False)  # RADAR, INDUCTIVE_LOOP, MICROWAVE, LIDAR
    name = Column(String(128), nullable=False)
    telemetry_endpoint = Column(String(255), nullable=True)
    health_status = Column(String(32), default="DISCONNECTED")  # CONNECTED, DISCONNECTED, STALE
    last_observation_timestamp = Column(DateTime, nullable=True)
    quality = Column(String(32), default="UNKNOWN")  # FRESH, AGING, STALE, INVALID

    intersection = relationship("Intersection", back_populates="sensors")


# ==========================================
# 5. Computer Vision Detections & Tracks
# ==========================================

class VehicleDetection(Base):
    __tablename__ = "vehicle_detections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    camera_id = Column(String(36), ForeignKey("cameras.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    class_name = Column(String(32), nullable=False)  # car, truck, bus, motorcycle, bicycle, emergency_vehicle
    confidence = Column(Float, nullable=False)
    bbox_x = Column(Float, nullable=False)
    bbox_y = Column(Float, nullable=False)
    bbox_w = Column(Float, nullable=False)
    bbox_h = Column(Float, nullable=False)
    track_id = Column(Integer, nullable=True)
    lane_id = Column(String(36), nullable=True)

    camera = relationship("Camera", back_populates="detections")


class VehicleTrack(Base):
    __tablename__ = "vehicle_tracks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    camera_id = Column(String(36), nullable=False)
    track_id = Column(Integer, nullable=False)
    class_name = Column(String(32), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    speed_kph = Column(Float, nullable=True)
    dwell_time_sec = Column(Float, nullable=True)
    trajectory = Column(JSON, nullable=True)  # List of [x, y, timestamp]


# ==========================================
# 6. Real Traffic Telemetry, Metrics & Provenance
# ==========================================

class TrafficObservation(Base):
    __tablename__ = "traffic_observations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), nullable=False, index=True)
    lane_id = Column(String(36), nullable=True)
    source = Column(String(64), nullable=False)      # e.g., camera_01, radar_north, inductive_loop_3
    source_id = Column(String(64), nullable=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    vehicle_count = Column(Integer, nullable=False)
    occupancy_pct = Column(Float, nullable=True)
    avg_speed_kph = Column(Float, nullable=True)
    quality = Column(String(32), default="FRESH")     # FRESH, AGING, STALE, INVALID
    provenance = Column(JSON, nullable=True)


class TrafficMetric(Base):
    __tablename__ = "traffic_metrics"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), ForeignKey("intersections.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    vehicle_count = Column(Integer, nullable=True)
    flow_rate_vph = Column(Float, nullable=True)
    occupancy_pct = Column(Float, nullable=True)
    avg_speed_kph = Column(Float, nullable=True)
    queue_length_meters = Column(Float, nullable=True)
    avg_wait_time_sec = Column(Float, nullable=True)
    traffic_pressure = Column(Float, nullable=True)
    # Observation window the flow rate was extrapolated from. Null means the
    # window was not recorded, and flow_rate_vph must not be trusted.
    sample_window_sec = Column(Float, nullable=True)
    data_quality = Column(String(32), default="NO_DATA")  # FRESH, AGING, STALE, NO_DATA
    calculation_method = Column(String(64), nullable=False)
    provenance = Column(JSON, nullable=True)

    intersection = relationship("Intersection", back_populates="traffic_metrics")


# ==========================================
# 7. Incidents & Priority Events
# ==========================================

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), ForeignKey("intersections.id"), nullable=False)
    title = Column(String(128), nullable=False)
    type = Column(String(64), nullable=False)  # SUDDEN_STOPPAGE, ROAD_OBSTRUCTION, ACCIDENT_PATTERN, LANE_BLOCKAGE
    severity = Column(String(32), default="MEDIUM")  # LOW, MEDIUM, HIGH, CRITICAL
    status = Column(String(32), default="DETECTED")  # DETECTED -> SUSPECTED -> VERIFIED -> ACTIVE -> MITIGATED -> RESOLVED
    detected_at = Column(DateTime, default=utc_now, index=True)
    verified_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    affected_lanes = Column(JSON, default=list)
    confidence = Column(Float, default=1.0)
    source = Column(String(64), nullable=False)
    evidence = Column(JSON, nullable=True)
    operator_notes = Column(Text, nullable=True)

    # --- Triage & assignment --------------------------------------------
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(String(64), nullable=True)
    assigned_to = Column(String(64), nullable=True)
    assigned_at = Column(DateTime, nullable=True)

    # --- SLA -------------------------------------------------------------
    #: Targets in seconds, copied from policy when the incident is created so
    #: a later policy change does not retroactively rewrite whether a past
    #: incident met its target.
    sla_acknowledge_sec = Column(Integer, nullable=True)
    sla_resolve_sec = Column(Integer, nullable=True)
    sla_acknowledge_breached = Column(Boolean, default=False, nullable=False)
    sla_resolve_breached = Column(Boolean, default=False, nullable=False)

    intersection = relationship("Intersection", back_populates="incidents")


class EmergencyEvent(Base):
    __tablename__ = "emergency_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), nullable=False)
    vehicle_id = Column(String(64), nullable=False)
    vehicle_type = Column(String(32), nullable=False)  # AMBULANCE, FIRE_TRUCK, POLICE
    priority_level = Column(Integer, default=1)        # 1 = Highest
    status = Column(String(32), default="ACTIVE")      # ACTIVE, CLEARED, REJECTED
    timestamp = Column(DateTime, default=utc_now)
    requested_phase = Column(Integer, nullable=True)
    safety_clearance_passed = Column(Boolean, default=False)
    safety_report = Column(JSON, nullable=True)  # Full DeterministicSafetyEngine verdict
    source = Column(String(64), nullable=False)

    #: MANUAL (operator request) or AVL (vehicle position feed). Both paths go
    #: through the same Safety Engine validation and the same dispatcher.
    trigger = Column(String(16), nullable=False, default="MANUAL")
    #: The SignalCommand the dispatcher recorded, and its real outcome.
    command_id = Column(String(36), nullable=True)
    command_status = Column(String(32), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    heading_deg = Column(Float, nullable=True)
    eta_sec = Column(Float, nullable=True)
    position_reported_at = Column(DateTime, nullable=True)
    details = Column(JSON, nullable=True)


class TransitEvent(Base):
    __tablename__ = "transit_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    route_id = Column(String(64), nullable=False)
    vehicle_id = Column(String(64), nullable=False)
    intersection_id = Column(String(36), nullable=False)
    delay_seconds = Column(Integer, default=0)
    priority_requested = Column(Boolean, default=False)
    priority_granted = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=utc_now)
    source = Column(String(64), default="GTFS-RT")

    trip_id = Column(String(64), nullable=True)
    #: The conditional-TSP decision and its reason, recorded for every bus
    #: evaluated - including the ones not granted, so the record shows why.
    decision = Column(String(48), nullable=True)
    decision_reason = Column(Text, nullable=True)
    command_id = Column(String(36), nullable=True)
    distance_m = Column(Float, nullable=True)
    bearing_deg = Column(Float, nullable=True)
    vehicle_reported_at = Column(DateTime, nullable=True)
    details = Column(JSON, nullable=True)


# ==========================================
# 8. Weather & Environmental Data
# ==========================================

class WeatherObservation(Base):
    __tablename__ = "weather_observations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    temperature_c = Column(Float, nullable=True)
    precipitation_mm = Column(Float, nullable=True)
    wind_speed_kph = Column(Float, nullable=True)
    visibility_meters = Column(Float, nullable=True)
    weather_code = Column(Integer, nullable=True)
    road_condition = Column(String(32), default="DRY")  # DRY, WET, FLOODED, ICY
    timestamp = Column(DateTime, default=utc_now, index=True)
    source = Column(String(64), nullable=False)         # e.g., Open-Meteo, Roadside Weather Station


# ==========================================
# 9. AI Models & Reproducible Decision Ledger
# ==========================================

class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(128), nullable=False)
    task = Column(String(64), nullable=False)        # VEHICLE_DETECTION, SIGNAL_OPTIMIZATION, INCIDENT_DETECTION
    version = Column(String(32), nullable=False)
    provider = Column(String(64), nullable=False)    # PyTorch, ONNX, Scikit-learn, XGBoost
    training_dataset = Column(String(128), nullable=True)
    evaluation_metrics = Column(JSON, nullable=True)  # MAE, RMSE, Precision, Recall, F1
    status = Column(String(32), default="VALIDATION") # TRAINING, VALIDATION, SHADOW, APPROVED, ACTIVE, RETIRED
    created_at = Column(DateTime, default=utc_now)
    activated_at = Column(DateTime, nullable=True)


class AIDecision(Base):
    __tablename__ = "ai_decisions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), nullable=False, index=True)
    model_id = Column(String(36), nullable=False)
    model_version = Column(String(32), nullable=False)
    input_snapshot = Column(JSON, nullable=False)       # Exact input telemetry snapshot
    proposed_action = Column(JSON, nullable=False)      # Proposed phase or green extension
    safety_validation = Column(JSON, nullable=False)    # Detailed result of Deterministic Safety Engine check
    execution_status = Column(String(32), nullable=False) # EXECUTED, REJECTED_BY_SAFETY, OVERRIDDEN, NO_CHANGE
    created_at = Column(DateTime, default=utc_now, index=True)


# ==========================================
# 10. Operational Alerts & Maintenance
# ==========================================

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    severity = Column(String(32), nullable=False)  # INFO, WARNING, CRITICAL
    category = Column(String(64), nullable=False)  # SAFETY, HARDWARE, TELEMETRY_STALE, INCIDENT
    title = Column(String(128), nullable=False)
    message = Column(Text, nullable=False)
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(String(64), nullable=True)
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(64), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, default=utc_now, index=True)

    # --- Rules engine linkage -------------------------------------------
    rule_id = Column(String(36), nullable=True, index=True)
    #: Stable key identifying "the same alert" for dedupe: rule + subject.
    dedupe_key = Column(String(160), nullable=True, index=True)
    #: The measured values that caused this alert - provenance for the alert
    #: itself, so an operator can see what the rule actually saw.
    observed = Column(JSON, nullable=True)
    #: Incremented instead of creating a duplicate row while in cooldown.
    occurrence_count = Column(Integer, default=1, nullable=False)
    last_occurrence_at = Column(DateTime, default=utc_now)
    escalated = Column(Boolean, default=False, nullable=False)
    escalated_at = Column(DateTime, nullable=True)
    original_severity = Column(String(32), nullable=True)


class MaintenanceEvent(Base):
    __tablename__ = "maintenance_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(36), nullable=False)
    title = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), default="SCHEDULED")  # SCHEDULED, IN_PROGRESS, COMPLETED
    scheduled_date = Column(DateTime, nullable=False)
    completed_date = Column(DateTime, nullable=True)
    technician_name = Column(String(64), nullable=True)


# ==========================================
# 11. Grounded RAG Knowledge Base
# ==========================================

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)     # SOP, NEMA_STANDARD, CONTROLLER_MANUAL, SAFETY_POLICY
    source_filename = Column(String(255), nullable=False)
    checksum = Column(String(64), nullable=False)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("knowledge_documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)

    document = relationship("KnowledgeDocument", back_populates="chunks")


# ==========================================
# 12. Alert Rules Engine
# ==========================================

class AlertRule(Base):
    """An operator-defined condition evaluated against real stored state.

    Rules never invent inputs: a rule whose subject has reported nothing
    evaluates to INSUFFICIENT_DATA, not to false.
    """

    __tablename__ = "alert_rules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    #: Condition type, e.g. DETECTOR_SILENT, OCCUPANCY_SUSTAINED,
    #: CONTROLLER_STATE, PROVIDER_DEGRADED, COMMAND_REJECTED.
    condition_type = Column(String(48), nullable=False, index=True)
    #: Typed parameters for the condition (thresholds, durations, targets).
    parameters = Column(JSON, nullable=False, default=dict)
    #: Optional scope: evaluate only for this intersection.
    intersection_id = Column(String(36), nullable=True, index=True)

    severity = Column(String(32), default="WARNING", nullable=False)  # INFO, WARNING, CRITICAL
    enabled = Column(Boolean, default=True, nullable=False)

    #: Seconds before the same rule+subject may fire again.
    cooldown_sec = Column(Integer, default=300, nullable=False)
    #: Seconds an unacknowledged alert waits before escalating.
    escalate_after_sec = Column(Integer, nullable=True)
    escalate_to_severity = Column(String(32), nullable=True)

    #: Delivery channels: ["UI"], ["UI", "WEBHOOK"], ["UI", "EMAIL"], ...
    delivery_channels = Column(JSON, default=lambda: ["UI"])
    webhook_url = Column(String(512), nullable=True)
    email_to = Column(String(512), nullable=True)

    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    last_evaluated_at = Column(DateTime, nullable=True)
    last_fired_at = Column(DateTime, nullable=True)
    fire_count = Column(Integer, default=0, nullable=False)


class RuleEvaluation(Base):
    """One evaluation of one rule, kept so a firing can be explained."""

    __tablename__ = "rule_evaluations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    rule_id = Column(String(36), ForeignKey("alert_rules.id"), nullable=False, index=True)
    subject_type = Column(String(48), nullable=False)   # Sensor, SignalController, Provider
    subject_id = Column(String(64), nullable=True)
    #: MATCHED, NOT_MATCHED, INSUFFICIENT_DATA, SUPPRESSED_COOLDOWN, SUPPRESSED_DUPLICATE
    outcome = Column(String(32), nullable=False, index=True)
    #: The measured values the outcome rests on.
    observed = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    alert_id = Column(String(36), nullable=True)
    evaluated_at = Column(DateTime, default=utc_now, index=True)


class AlertDelivery(Base):
    """One delivery attempt of one alert to one channel."""

    __tablename__ = "alert_deliveries"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    alert_id = Column(String(36), nullable=False, index=True)
    channel = Column(String(32), nullable=False)        # UI, WEBHOOK, EMAIL
    target = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False)          # DELIVERED, FAILED, SKIPPED_NOT_CONFIGURED
    detail = Column(Text, nullable=True)
    attempted_at = Column(DateTime, default=utc_now, index=True)


# ==========================================
# 13. Observed Signal State History
# ==========================================

class SignalStateLog(Base):
    """One observed reading of a controller's phase state.

    Written on every successful controller poll. This is the raw material for
    every signal performance measure the platform reports: arrival-on-green,
    split failures, progression and the corridor time-space diagram all need to
    know which phase was green at a given instant, and none of them can be
    computed from a current-state snapshot.

    Rows are observations, never predictions: a gap in this table is a period
    the platform genuinely did not observe, and the analytics treat it as such
    rather than assuming the signal carried on cycling.
    """

    __tablename__ = "signal_state_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    controller_id = Column(String(36), nullable=False, index=True)
    intersection_id = Column(String(36), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)

    green_phases = Column(JSON, nullable=True)     # list[int]
    yellow_phases = Column(JSON, nullable=True)    # list[int]
    red_phases = Column(JSON, nullable=True)       # list[int]

    #: How the reading was obtained, e.g. NTCIP_1202_POLL.
    source = Column(String(64), nullable=False)
    read_latency_ms = Column(Float, nullable=True)


# ==========================================
# 14. Scenario Sandbox (HYPOTHETICAL ONLY)
# ==========================================

class ScenarioRun(Base):
    """A hypothetical timing scenario. NEVER observed data.

    This table is deliberately separate from `traffic_metrics` rather than a
    flag on it. A flag is one forgotten WHERE clause away from a hypothetical
    number appearing on the operations map as a measurement; a separate table
    with different column names cannot be mixed in by accident.

    Nothing in the platform reads this table except the scenario endpoints.
    """

    __tablename__ = "scenario_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), nullable=True, index=True)
    label = Column(String(128), nullable=False)
    operator = Column(String(64), nullable=False)

    #: Volumes and geometry the operator entered. Never generated.
    input_movements = Column(JSON, nullable=False)

    scenario_cycle_length_sec = Column(Integer, nullable=True)
    scenario_splits = Column(JSON, nullable=True)
    scenario_expected_delay = Column(JSON, nullable=True)
    calculation_trace = Column(JSON, nullable=True)

    status = Column(String(32), nullable=False)          # COMPUTED, REFUSED
    refusal_reason = Column(String(64), nullable=True)

    #: Real measured comparison, or an explicit insufficiency.
    measured_baseline = Column(JSON, nullable=True)
    comparison = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=utc_now, index=True)


class OptimizerRecommendation(Base):
    """An optimiser proposal produced from real or operator-entered demand.

    Distinct from ScenarioRun: a recommendation is intended to be acted on and
    therefore carries a Safety Engine verdict. A scenario is never actionable.
    """

    __tablename__ = "optimizer_recommendations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    intersection_id = Column(String(36), nullable=False, index=True)
    controller_id = Column(String(36), nullable=True)
    method_version = Column(String(48), nullable=False)

    #: Where the demand came from: MEASURED_DETECTOR or OPERATOR_ENTERED.
    demand_source = Column(String(48), nullable=False)
    inputs = Column(JSON, nullable=False)
    #: Inputs the method expects that were not available.
    missing_inputs = Column(JSON, nullable=True)

    status = Column(String(32), nullable=False)          # COMPUTED, REFUSED
    refusal_reason = Column(String(64), nullable=True)
    proposed_cycle_length_sec = Column(Integer, nullable=True)
    proposed_splits = Column(JSON, nullable=True)
    expected_delay = Column(JSON, nullable=True)
    calculation_trace = Column(JSON, nullable=True)

    #: Full DeterministicSafetyEngine verdict on the proposal.
    safety_verdict = Column(JSON, nullable=True)
    safety_passed = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=utc_now, index=True)
    created_by = Column(String(64), nullable=True)


# ==========================================
# 15. API Keys (machine callers)
# ==========================================

class ApiKey(Base):
    """A scoped credential for machine callers.

    Only a SHA-256 hash of the key is stored: a database disclosure does not
    hand over working credentials. The plaintext exists exactly once, in the
    creation response.
    """

    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(128), nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    #: Leading characters, so a key is recognisable in a list without being
    #: recoverable from it.
    key_prefix = Column(String(24), nullable=False)
    scopes = Column(JSON, nullable=False, default=list)

    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, default=0, nullable=False)


# ==========================================
# 16. Incident Timeline & Evidence
# ==========================================

class IncidentTimelineEntry(Base):
    """One append-only entry in an incident's history.

    Append-only by convention and by API: there is no update or delete path.
    An incident review is worthless if the timeline can be edited afterwards,
    so a correction is a new entry that references the one it corrects.
    """

    __tablename__ = "incident_timeline"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    incident_id = Column(String(36), ForeignKey("incidents.id"), nullable=False, index=True)
    #: STATUS_CHANGE, NOTE, ASSIGNMENT, EVIDENCE_ATTACHED, SLA_BREACH, CORRECTION
    entry_type = Column(String(32), nullable=False, index=True)
    actor = Column(String(64), nullable=False)
    summary = Column(String(255), nullable=False)
    detail = Column(Text, nullable=True)
    #: Machine-readable context: from/to status, sla seconds, evidence id.
    context = Column(JSON, nullable=True)
    #: When this entry corrects an earlier one.
    corrects_entry_id = Column(String(36), nullable=True)
    timestamp = Column(DateTime, default=utc_now, index=True)


class IncidentEvidence(Base):
    """A real artefact attached to an incident.

    Only references to things the platform actually recorded: a camera frame
    it ingested, a sensor observation it stored, a signal command it issued.
    There is no free-form upload path, because an "evidence" item nobody can
    trace back to a recorded observation is an assertion, not evidence.
    """

    __tablename__ = "incident_evidence"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    incident_id = Column(String(36), ForeignKey("incidents.id"), nullable=False, index=True)
    #: CAMERA_FRAME, SENSOR_OBSERVATION, TRAFFIC_METRIC, SIGNAL_COMMAND, SIGNAL_STATE
    evidence_type = Column(String(32), nullable=False)
    #: The table and row this evidence points at.
    source_table = Column(String(64), nullable=False)
    source_id = Column(String(64), nullable=False)
    #: Snapshot of the referenced record at attachment time, so the evidence
    #: survives even if the source row is later pruned by retention.
    snapshot = Column(JSON, nullable=False)
    observed_at = Column(DateTime, nullable=True)
    attached_by = Column(String(64), nullable=False)
    attached_at = Column(DateTime, default=utc_now, index=True)
    note = Column(Text, nullable=True)


# ==========================================
# 17. Operator Shift Handover
# ==========================================

class ShiftHandover(Base):
    """A shift handover record: auto-generated, edited, then signed off.

    The generated snapshot is kept separately from the operator's notes and is
    never overwritten by editing. A handover is the document the next shift
    relies on, and being able to see what the platform reported alongside what
    the operator added is the difference between a record and a summary.

    Once signed off, the record is immutable by API: a handover that can be
    revised after the fact cannot be relied on by the shift that read it.
    """

    __tablename__ = "shift_handovers"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    #: Shift boundaries the handover covers.
    shift_start = Column(DateTime, nullable=False)
    shift_end = Column(DateTime, nullable=False)

    outgoing_operator = Column(String(64), nullable=False)
    incoming_operator = Column(String(64), nullable=True)

    #: What the platform reported at generation time. Never edited.
    generated_snapshot = Column(JSON, nullable=False)
    generated_at = Column(DateTime, default=utc_now, nullable=False)

    #: What the operator added. Edited freely until sign-off.
    operator_notes = Column(Text, nullable=True)
    #: Items the outgoing operator flags for the incoming one.
    pending_actions = Column(JSON, default=list)

    status = Column(String(32), default="DRAFT", nullable=False)  # DRAFT, SIGNED_OFF
    signed_off_at = Column(DateTime, nullable=True)
    signed_off_by = Column(String(64), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(String(64), nullable=True)


class CoordinationPlan(Base):
    """A green-wave timing plan for a corridor: proposed, validated, applied.

    Stored before anything reaches a controller, so what was proposed, what the
    Safety Engine said about it, and what each controller actually accepted
    stay separate records. A plan that applied on two controllers and failed on
    the third is PARTIALLY_APPLIED with each outcome listed - never summarised
    as applied.
    """

    __tablename__ = "coordination_plans"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    corridor_id = Column(String(36), ForeignKey("corridors.id"), nullable=False, index=True)

    #: PROPOSED, REJECTED_BY_SAFETY, REJECTED_AT_APPLY, APPLIED,
    #: PARTIALLY_APPLIED, APPLY_FAILED
    status = Column(String(32), nullable=False, default="PROPOSED")
    direction = Column(String(16), nullable=False)
    design_speed_kph = Column(Float, nullable=False)
    #: OPERATOR_ENTERED or CONFIGURED_SPEED_LIMIT - never measured.
    speed_basis = Column(String(32), nullable=False)
    cycle_sec = Column(Integer, nullable=False)
    cycle_basis = Column(String(48), nullable=False)
    coord_phase = Column(Integer, nullable=False)

    junction_plans = Column(JSON, nullable=False)
    bandwidth = Column(JSON, nullable=True)
    safety_summary = Column(JSON, nullable=True)
    uncoordinated = Column(JSON, nullable=True)

    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    applied_by = Column(String(64), nullable=True)
    applied_at = Column(DateTime, nullable=True)
    apply_results = Column(JSON, nullable=True)


class PollerLease(Base):
    """Single-writer lease for the controller poller.

    The poller runs in-process, so two API replicas would otherwise both poll
    every controller and write two `signal_state_logs` rows per observation -
    silently doubling every measure derived from that log. A doubled
    measurement is worse than an outage: an outage is visible, while a doubled
    throughput just looks like a busy junction.

    The row is inspectable on purpose. An operator needs to be able to see
    which instance is doing the writing, and a lease that expires on a
    heartbeat recovers by itself when its holder dies, which a lock held by a
    wedged process does not.
    """

    __tablename__ = "poller_leases"

    #: Lease name, not a surrogate key: there is one lease per named job, and
    #: the uniqueness constraint is what makes the election correct.
    name = Column(String(64), primary_key=True)

    #: host:pid:random of the instance currently holding the lease.
    holder_id = Column(String(128), nullable=False)

    acquired_at = Column(DateTime, nullable=False, default=utc_now)
    heartbeat_at = Column(DateTime, nullable=False, default=utc_now)


# ==========================================
# Audit ledger chaining
# ==========================================
#
# Registered here, at model-import time, rather than during application
# startup. An audit row written by a script, a migration helper or a test
# would otherwise be left unchained, and an unchained row is a silent gap in
# a ledger whose whole purpose is that gaps are not silent.
#
# The hashing itself is imported lazily inside the handler to avoid a circular
# import (ledger -> entities -> database).

def _install_audit_chaining() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session as _Session

    if getattr(_install_audit_chaining, "_installed", False):
        return

    @event.listens_for(_Session, "before_flush")
    def _chain_audit_entries(session, _flush_context, _instances):  # noqa: ANN001
        if not any(isinstance(obj, AuditLog) for obj in session.new):
            return
        from app.governance.ledger import stamp_pending_entries
        stamp_pending_entries(session)

    _install_audit_chaining._installed = True


_install_audit_chaining()
