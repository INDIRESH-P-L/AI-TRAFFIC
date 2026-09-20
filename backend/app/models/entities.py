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
    source = Column(String(64), nullable=False)


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
