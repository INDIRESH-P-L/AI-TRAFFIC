"""TRAFFICINTEL AI - Domain Schemas (Pydantic v2)

Typed request/response data transfer objects.
Strict enforcement: nullable metrics for unobserved data, explicit provenance fields,
and validation objects for deterministic safety checks.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ==========================================
# Auth & User Schemas
# ==========================================

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    role: str = "OPERATOR"


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Infrastructure Schemas
# ==========================================

class LaneCreate(BaseModel):
    lane_number: int
    movement_type: str  # THRU, LEFT_TURN, RIGHT_TURN, THRU_RIGHT
    assigned_phase: Optional[int] = None


class LaneResponse(BaseModel):
    id: str
    lane_number: int
    movement_type: str
    assigned_phase: Optional[int] = None

    class Config:
        from_attributes = True


class ApproachCreate(BaseModel):
    direction: str  # NORTHBOUND, SOUTHBOUND, EASTBOUND, WESTBOUND
    road_name: str
    speed_limit_kph: int = 50
    lanes: List[LaneCreate] = []


class ApproachResponse(BaseModel):
    id: str
    direction: str
    road_name: str
    speed_limit_kph: int
    lanes: List[LaneResponse] = []

    class Config:
        from_attributes = True


class IntersectionCreate(BaseModel):
    name: str
    code: str
    latitude: float
    longitude: float
    jurisdiction: str = "Municipal DOT"
    corridor_id: Optional[str] = None
    approaches: List[ApproachCreate] = []


class IntersectionSummary(BaseModel):
    id: str
    name: str
    code: str
    latitude: float
    longitude: float
    jurisdiction: str
    operational_status: str
    controller_status: str = "NOT_CONNECTED"
    camera_status: str = "OFFLINE"
    active_incidents_count: int = 0

    class Config:
        from_attributes = True


class IntersectionDetail(BaseModel):
    id: str
    name: str
    code: str
    latitude: float
    longitude: float
    jurisdiction: str
    operational_status: str
    corridor_id: Optional[str] = None
    approaches: List[ApproachResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==========================================
# Signal Controller & Safety Schemas
# ==========================================

class SignalPhaseCreate(BaseModel):
    phase_number: int
    ring: int = 1
    barrier: int = 1
    name: str
    min_green: int = 7
    max_green: int = 65
    yellow_change: int = 4
    red_clearance: int = 2
    ped_walk: int = 7
    ped_clearance: int = 15
    conflicting_phases: List[int] = []


class SignalPhaseResponse(BaseModel):
    id: str
    phase_number: int
    ring: int
    barrier: int
    name: str
    min_green: int
    max_green: int
    yellow_change: int
    red_clearance: int
    ped_walk: int
    ped_clearance: int
    conflicting_phases: List[int] = []

    class Config:
        from_attributes = True


class SignalControllerCreate(BaseModel):
    intersection_id: str
    name: str
    vendor: str
    model: str
    protocol: str
    ip_address: str
    port: int = 501
    cycle_length: int = 90
    phases: List[SignalPhaseCreate] = []


class SignalControllerResponse(BaseModel):
    id: str
    intersection_id: str
    name: str
    vendor: str
    model: str
    protocol: str
    ip_address: str
    port: int
    connection_status: str
    control_mode: str
    active_phase: Optional[int] = None
    current_phase_start: Optional[datetime] = None
    cycle_length: int
    last_heartbeat: Optional[datetime] = None
    phases: List[SignalPhaseResponse] = []

    class Config:
        from_attributes = True


class SafetyCheckResult(BaseModel):
    is_safe: bool
    violations: List[str] = []
    checks_performed: List[str] = []
    details: Dict[str, Any] = {}


class SignalCommandRequest(BaseModel):
    controller_id: str
    requested_phase: int
    command_type: str = "PHASE_HOLD"  # PHASE_HOLD, FORCE_OFF, CALL
    duration_sec: int = Field(default=15, ge=5, le=120)
    idempotency_key: str


class SignalCommandResponse(BaseModel):
    command_id: str
    idempotency_key: str
    controller_id: str
    requested_phase: int
    status: str  # EXECUTED, REJECTED, FAILED, TIMED_OUT
    safety_check_passed: bool
    safety_report: SafetyCheckResult
    issued_at: datetime
    acknowledged_at: Optional[datetime] = None


# ==========================================
# Real Telemetry & Quality Schemas
# ==========================================

class TelemetryDataPoint(BaseModel):
    source: str
    source_id: Optional[str] = None
    timestamp: datetime
    quality: str  # FRESH, AGING, STALE, INVALID
    measurement: str
    value: Optional[float] = None
    confidence: Optional[float] = None
    provenance: Optional[Dict[str, Any]] = None


class TrafficMetricResponse(BaseModel):
    intersection_id: str
    timestamp: Optional[datetime] = None
    vehicle_count: Optional[int] = None
    flow_rate_vph: Optional[float] = None
    occupancy_pct: Optional[float] = None
    avg_speed_kph: Optional[float] = None
    queue_length_meters: Optional[float] = None
    avg_wait_time_sec: Optional[float] = None
    traffic_pressure: Optional[float] = None
    data_quality: str = "NO_DATA"  # FRESH, AGING, STALE, NO_DATA
    calculation_method: str = "UNAVAILABLE"
    provenance: Optional[Dict[str, Any]] = None


# ==========================================
# Incidents & Priority Feeds
# ==========================================

class IncidentCreate(BaseModel):
    intersection_id: str
    title: str
    type: str
    severity: str = "MEDIUM"
    source: str
    affected_lanes: List[int] = []
    evidence: Optional[Dict[str, Any]] = None
    operator_notes: Optional[str] = None


class IncidentStatusUpdate(BaseModel):
    status: str  # DETECTED, SUSPECTED, VERIFIED, ACTIVE, MITIGATED, RESOLVED
    operator_notes: Optional[str] = None


class IncidentResponse(BaseModel):
    id: str
    intersection_id: str
    title: str
    type: str
    severity: str
    status: str
    detected_at: datetime
    verified_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    affected_lanes: List[Any] = []
    confidence: float
    source: str
    evidence: Optional[Dict[str, Any]] = None
    operator_notes: Optional[str] = None

    class Config:
        from_attributes = True


# ==========================================
# Weather Schema
# ==========================================

class WeatherResponse(BaseModel):
    latitude: float
    longitude: float
    temperature_c: Optional[float] = None
    precipitation_mm: Optional[float] = None
    wind_speed_kph: Optional[float] = None
    visibility_meters: Optional[float] = None
    road_condition: str = "UNKNOWN"
    status: str = "WEATHER_DATA_UNAVAILABLE"
    source: Optional[str] = None
    timestamp: Optional[datetime] = None


# ==========================================
# Audit & AI Copilot Schemas
# ==========================================

class AuditLogResponse(BaseModel):
    id: str
    actor_username: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    result: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime

    class Config:
        from_attributes = True


class CopilotQuery(BaseModel):
    query: str
    intersection_id: Optional[str] = None


class CopilotResponse(BaseModel):
    query: str
    answer: str
    grounding_data_used: List[str] = []
    telemetry_state: str  # REAL_TELEMETRY_AVAILABLE, NO_LIVE_TELEMETRY, INSUFFICIENT_DATA
    citations: List[Dict[str, Any]] = []
    suggested_actions: List[Dict[str, Any]] = []
