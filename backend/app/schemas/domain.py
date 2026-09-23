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


class SafetyCheck(BaseModel):
    """One deterministic rule's verdict, rendered as its own row in the console."""

    code: str                       # e.g. PHASE_CONFLICT_MATRIX_VALIDATION
    label: str                      # e.g. "Phase conflict matrix"
    passed: bool
    detail: str                     # plain-language explanation, pass or fail
    standard: Optional[str] = None  # the standard the rule derives from


class SafetyCheckResult(BaseModel):
    is_safe: bool
    violations: List[str] = []           # details of failed checks
    checks_performed: List[str] = []     # codes of every rule evaluated
    checks: List[SafetyCheck] = []       # per-rule verdicts, in evaluation order
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


class PreemptionRequest(BaseModel):
    """Emergency vehicle preemption call.

    Carried as a request body (the operations console posts JSON). The
    requested phase is validated by the Deterministic Safety Engine exactly
    like any other signal command - preemption raises priority, never the
    permission to create a conflict.
    """

    intersection_id: str
    vehicle_id: str
    vehicle_type: str  # AMBULANCE, FIRE_TRUCK, POLICE
    requested_phase: int
    priority_level: int = Field(default=1, ge=1, le=5)
    source: str = "OPERATOR_CONSOLE"
    dwell_sec: Optional[int] = Field(
        default=None,
        description="Requested green dwell. Defaults to the target phase's configured minimum green.",
    )


class PreemptionResponse(BaseModel):
    event_id: str
    intersection_id: str
    vehicle_id: str
    vehicle_type: str
    requested_phase: int
    status: str  # ACTIVE, REJECTED
    safety_clearance_passed: bool
    safety_report: SafetyCheckResult
    controller_id: Optional[str] = None
    timestamp: datetime


class SignalCommandPreview(BaseModel):
    """Result of a dry-run validation. Nothing was written and nothing was sent."""

    controller_id: str
    controller_name: str
    requested_phase: int
    duration_sec: int
    would_be_accepted: bool
    safety_report: SafetyCheckResult
    controller_state: Optional[Dict[str, Any]] = None
    evaluated_at: datetime


class AlertRuleCreate(BaseModel):
    """A rule an operator defines. Evaluated only against stored real state."""

    name: str
    description: Optional[str] = None
    condition_type: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    intersection_id: Optional[str] = None
    severity: str = "WARNING"
    enabled: bool = True
    cooldown_sec: int = Field(default=300, ge=0, le=86400)
    escalate_after_sec: Optional[int] = Field(default=None, ge=0, le=86400)
    escalate_to_severity: Optional[str] = None
    delivery_channels: List[str] = Field(default_factory=lambda: ["UI"])
    webhook_url: Optional[str] = None
    email_to: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    severity: Optional[str] = None
    enabled: Optional[bool] = None
    cooldown_sec: Optional[int] = Field(default=None, ge=0, le=86400)
    escalate_after_sec: Optional[int] = Field(default=None, ge=0, le=86400)
    escalate_to_severity: Optional[str] = None
    delivery_channels: Optional[List[str]] = None
    webhook_url: Optional[str] = None
    email_to: Optional[str] = None


class AlertRuleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    condition_type: str
    parameters: Dict[str, Any]
    intersection_id: Optional[str] = None
    severity: str
    enabled: bool
    cooldown_sec: int
    escalate_after_sec: Optional[int] = None
    escalate_to_severity: Optional[str] = None
    delivery_channels: Optional[List[str]] = None
    webhook_url: Optional[str] = None
    email_to: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    last_evaluated_at: Optional[datetime] = None
    last_fired_at: Optional[datetime] = None
    fire_count: int = 0

    class Config:
        from_attributes = True


class MovementInput(BaseModel):
    """Demand on one movement. Volumes are supplied, never generated."""

    phase_number: int
    name: Optional[str] = None
    volume_vph: float = Field(ge=0, le=10000)
    lanes: int = Field(default=1, ge=1, le=8)
    saturation_flow_vphpl: Optional[float] = Field(default=None, ge=500, le=2400)
    min_green_sec: int = Field(default=7, ge=1, le=120)
    max_green_sec: int = Field(default=65, ge=5, le=300)
    source: Optional[str] = None
    sample_size: int = 0


class OptimizerRequest(BaseModel):
    """Ask for a timing proposal.

    With no `movements`, demand is read from measured telemetry over
    `window_minutes`. With `movements`, the operator's volumes are used and
    the result is labelled as operator-entered.
    """

    intersection_id: str
    movements: Optional[List[MovementInput]] = None
    window_minutes: int = Field(default=60, ge=5, le=1440)


class ScenarioRequest(BaseModel):
    """Run a hypothetical. Output is stamped SCENARIO and stored separately."""

    intersection_id: Optional[str] = None
    label: str
    movements: List[MovementInput]
    lost_time_per_phase_sec: float = Field(default=4.0, ge=0.0, le=20.0)
    compare_to_measured: bool = False
    baseline_window_minutes: int = Field(default=60, ge=5, le=1440)


class ApiKeyCreate(BaseModel):
    """Request a scoped machine credential.

    A key cannot hold a scope its creator lacks, and can never hold
    signal:command - issuing a signal change requires a named accountable
    operator, not a shared machine credential.
    """

    name: str
    scopes: List[str]
    expires_in_days: int = Field(default=90, ge=1, le=730)


class PendingAction(BaseModel):
    """One item the outgoing operator flags for the incoming one."""

    kind: str
    reference: Optional[str] = None
    summary: str
    #: AUTO_GENERATED items came from the platform; OPERATOR items were added
    #: by hand. Keeping them distinguishable means a reader can tell what the
    #: platform noticed from what a person noticed.
    source: str = "OPERATOR"
    done: bool = False


class HandoverCreate(BaseModel):
    shift_hours: int = Field(default=8, ge=1, le=24)
    incoming_operator: Optional[str] = None


class HandoverUpdate(BaseModel):
    operator_notes: Optional[str] = None
    pending_actions: Optional[List[PendingAction]] = None
