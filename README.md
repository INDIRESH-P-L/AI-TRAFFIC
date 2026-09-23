# TRAFFICINTEL AI
## Real-Time AI Traffic Intelligence & Adaptive Signal Management Platform
*REAL-TIME INTELLIGENCE FOR SAFER, SMARTER TRAFFIC*

---

## 1. Executive Summary

**TRAFFICINTEL AI** is a serious, production-grade Intelligent Transportation System (ITS) platform engineered for municipal traffic management centers and regional transportation authorities.

### Core Architectural Guarantees:
- **Zero Fake Data**: Strictly zero synthetic vehicle counts, zero fake camera streams, zero random generators (`Math.random()`), zero mock incident feeds, and zero "demo/simulation modes".
- **Truthful Telemetry States**: When data sources are unconfigured or disconnected, the system explicitly reports:
  - `SYSTEM READY - No traffic infrastructure is currently connected.`
  - `NO CAMERA CONNECTED`
  - `NO SENSOR DATA AVAILABLE`
  - `SIGNAL CONTROLLER: NOT CONNECTED`
  - `SIGNAL STATE: UNAVAILABLE`
  - `WEATHER DATA UNAVAILABLE`
  - `INSUFFICIENT DATA FOR RELIABLE FORECAST`
- **Deterministic Signal Safety Engine**: All signal control commands pass through mathematical validation enforcing NEMA TS 2 / 170 / 2070 dual-ring barrier conflict matrices, minimum/maximum green times, yellow change intervals, all-red clearance, and command freshness (<5.0s window). AI and operators can never override this safety layer.
- **Provider Architecture**: Real adapters for `SignalControllerProvider` (NTCIP 1202 over SNMPv1/UDP), `CameraProvider` (RTSP & ONVIF reachability), `TrafficSensorProvider` (radar, loop, microwave), and `WeatherProvider` (Open-Meteo GIS).
- **Reachability is not readability**: a controller on a protocol with no implemented session layer is marked `REACHABLE`, never `CONNECTED`. Its phase, plan and cycle position read as `null` with a machine-readable reason, and the Safety Engine refuses commands to it — a conflict check cannot be grounded in a phase nobody read.
- **Measured vs. configured**: every status the console shows is one of the two, and says which. A provider with a URL in settings is `CONFIGURED`; only a subsystem a request actually exercised is reported as reachable.
- **Grounded Operations AI Copilot**: LLM assistant querying live database state and indexed engineering standards (FHWA MUTCD Section 4D, NEMA TS 2, municipal SOPs). If an unobserved junction is queried, it truthfully states no live telemetry exists.
- **Human-Engineered Operations Console**: Restrained, high-density ITS console with 20 dedicated routes built in React, TypeScript, Leaflet GIS, and custom CSS design tokens. Light and dark themes, compact/comfortable density, and a wallboard mode for control-room displays.
- **Provenance on every number**: telemetry is rendered through a `MeasuredValue` component that cannot be used without supplying source, timestamp and quality state. Ages tick live, and a reading that goes stale while a panel is open changes state in place.
- **Quality-coloured operations map**: markers are coloured by data quality rather than by a status word, and clusters inherit the *worst* quality of their members so one degraded junction stays visible at city zoom.
- **Guided command workflow**: propose → validate → confirm → audit. The validation step is a true dry run of the real command path and renders one row per Safety Engine rule with a plain-language explanation.
- **Measured provider health**: heartbeat, latency, error rate and circuit-breaker state per provider, with hysteresis so a flapping endpoint does not flood the console. A provider nobody has probed is `UNKNOWN`, never healthy.
- **Real ATSPM performance measures** from observed signal state and stored telemetry: throughput, occupancy, space-mean speed, control delay with HCM level of service, split failures and arrival-on-green. Every measure reports its sample size and method, and distinguishes *too little data* from *a missing input entirely*.
- **Explainable optimiser**: Webster's optimum cycle length and HCM v/c with a full calculation trace, routed through the Safety Engine. It refuses over-saturated and thin-data cases rather than producing a number.
- **Scenario sandbox** stored in its own table, stamped `SCENARIO / HYPOTHETICAL`, with no path to a controller.
- **Tamper-evident audit ledger**: SHA-256 hash chain with verification and export, plus fine-grained scopes and hashed API keys.

---

## 2. System Architecture

```
                                  +--------------------------------------------------------+
                                  |              TRAFFICINTEL AI Web Console               |
                                  |       (React + TypeScript + Vite + Leaflet GIS)        |
                                  +---------------------------+----------------------------+
                                                              | HTTPS / WSS
                                                              v
+------------------------------------------------------------------------------------------+
|                                    API Gateway & Services (FastAPI)                      |
|  +---------------------+   +---------------------+   +--------------------------------+  |
|  | Auth & RBAC         |   | Real-Time Event Bus |   | Audit Logger & Trace Engine    |  |
|  | (JWT / API Keys)    |   | (WebSocket Manager) |   | (Immutable Action Ledger)      |  |
|  +---------------------+   +---------------------+   +--------------------------------+  |
|                                                                                          |
|  +------------------------------------------------------------------------------------+  |
|  |                               Core Domain Services                                 |  |
|  |  * Traffic State & Provenance Engine     * Data Quality & Freshness Engine         |  |
|  |  * Incident Detection & Lifecycle Engine * Sensor Fusion Engine (Kalman/Weighted)  |  |
|  |  * Real Computer Vision Frame Pipeline   * Explainable AI Signal Optimizer         |  |
|  |  * Grounded LLM Operations Copilot (RAG) * Telemetry Ingestion Hub                 |  |
|  |  * ATSPM Performance Measures            * Rules & Alerting Engine                 |  |
|  +-------------------------------------------+----------------------------------------+  |
|                                              |                                           |
|                                              v                                           |
|  +------------------------------------------------------------------------------------+  |
|  |                    OPERATOR INSIGHT LAYER (reads only recorded state)              |  |
|  |                                                                                    |  |
|  |  * Data-Quality Trust Score -> 5 weighted components; UNRATED (null) is not 0;     |  |
|  |    weights renormalised over scorable components; GATES the AI optimiser below 60  |  |
|  |    for MEASURED demand only - operator-entered volumes are never gated             |  |
|  |  * Post-Change Verification -> Welch's t-test + 95% CI; an interval containing     |  |
|  |    zero is NO_MEASURABLE_CHANGE, not a small win; settle period excluded           |  |
|  |  * Corridor Stringline -> green bands from OBSERVED state, gaps preserved and      |  |
|  |    never interpolated; no speed from a sub-resolution offset                       |  |
|  |  * Shift Handover -> machine snapshot (frozen) + operator notes + blind spots;     |  |
|  |    sign-off makes the record immutable                                             |  |
|  +-------------------------------------------+----------------------------------------+  |
|                                              |                                           |
|                                              v                                           |
|  +------------------------------------------------------------------------------------+  |
|  |                      DETERMINISTIC SIGNAL SAFETY ENGINE                            |  |
|  |  * Phase Conflict Matrix Check            * Min/Max Green Interval Verification    |  |
|  |  * Clearance Interval Occupancy Check     * Controller State Readability Gate      |  |
|  |  * Yellow Change & All-Red Clearance      * Pedestrian Walk & Clearance (FDW)     |  |
|  |  * Command Freshness (<5s window)         * Idempotency & Concurrency Validation   |  |
|  |  * Controller Capability Verification     * Hardware Operational State Lock        |  |
|  +-------------------------------------------+----------------------------------------+  |
|                                              | Verified Command Only                     |
|                                              v                                           |
|  +------------------------------------------------------------------------------------+  |
|  |                         Provider Abstraction & Adapter Layer                       |  |
|  |                                                                                    |  |
|  |  READABLE (real protocol session - state is read, commands are accepted)           |  |
|  |    * Ntcip1202Adapter -> SNMPv1/UDP: phaseStatusGroup bitmaps, phaseControlGroup   |  |
|  |      hold, post-command read-back as evidence                                      |  |
|  |                                                                                    |  |
|  |  REACHABILITY ONLY (port answers; state unreadable, commands REFUSED)              |  |
|  |    * ReachabilityOnlyAdapter -> ASC/3 Ethernet, REST gateways, plain TCP           |  |
|  |      reports null phase/plan/cycle + UNREADABLE_NO_PROTOCOL_SESSION                |  |
|  |                                                                                    |  |
|  |    * CameraProvider (RTSP/ONVIF reachability; stream properties null until frames) |  |
|  |    * TrafficSensorProvider (Radar, Induction Loop, Microwave, Roadside IoT)        |  |
|  |    * WeatherProvider (Real Open-Meteo GIS Ingestion & API adapters)                |  |
|  |    * TransitProvider (GTFS & GTFS-Realtime) / EmergencyDataProvider                |  |
|  +-------------------------------------------+----------------------------------------+  |
+----------------------------------------------+-------------------------------------------+
                                               |
                       Observed state only     |     (never the requested state)
                                               v
+------------------------------------------------------------------------------------------+
|                             Storage & Persistence Layer                                  |
|  * PostgreSQL + PostGIS (Production) / Dual-Dialect SQLAlchemy 2.0 Engine                |
|  * Alembic-managed schema; the API verifies the revision at startup and refuses to      |
|    boot on drift in production                                                           |
|  * Normalized domain tables with Source Provenance, Data Quality and declared            |
|    calculation assumptions stamped on every derived metric                               |
|  * Clean initial state: zero fake operational records, zero seeded traffic numbers       |
+------------------------------------------------------------------------------------------+
```

---

## 3. Quick Start & Execution

### Prerequisites
- Python 3.12+
- Node.js v20+ and npm

### 1. Backend Setup & Run
```bash
cd backend
python -m pip install -r requirements.txt

# Bootstrap clean database (applies Alembic migrations & creates the initial administrator)
python -m app.db_init

# Launch API server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Upgrading an existing database** created before migrations were introduced:

```bash
cd backend
python -m alembic stamp 0001_baseline   # adopt the pre-existing schema
python -m alembic upgrade head          # apply Phase 0 columns
```

Alembic owns the schema. The API verifies the stamped revision at startup: it
warns in development and refuses to boot in production when the database has
drifted from the models.
Backend will be active at `http://127.0.0.1:8000`. OpenAPI docs available at `http://127.0.0.1:8000/docs`.

### 2. Frontend Setup & Run
```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
Frontend console will be active at `http://127.0.0.1:5173`.

### 3. Default Credentials
- **Username**: `admin`
- **Password**: `TrafficIntel2026!`
- **Role**: `ADMIN`

---

## 4. Automated Test Suite

Run the automated pytest suite:
```bash
cd backend
python -m pytest -v
```

All 160 tests validate deterministic safety, data quality transitions, protocol
integration and zero-fake-data invariants. The suite runs against a throwaway
database built through the real migrations; it never touches `trafficintel.db`.

Safety & quality:
- Conflict matrix rejection of concurrent conflicting greens
- Clearance-interval conflicts: a phase in yellow or all-red still occupies
  the intersection, even though no phase reads green
- Minimum green active phase hold enforcement
- Stale command expiration protection (<5.0s window)
- Disconnected and unreadable hardware command locks
- Quality state transitions (`FRESH` → `AGING` → `STALE` → `DISCONNECTED`)
- Naive/aware timestamp handling for controllers loaded from the database

Truthfulness:
- Adapters never report a phase, plan or cycle position they did not read
- Adapters without a command channel refuse rather than acknowledge
- Camera adapters return null stream properties, never typical-looking values
- Unreadable controllers clear stale phase state instead of leaving it live
- Flow rate is null without a declared sample window; traffic pressure is null
  without observed occupancy; aggregate freshness follows the oldest input
- Forecasts report no registered model rather than invented error metrics

Protocol & lifecycle:
- SNMPv1/BER codec round-trips GET, SET and Response; malformed payloads raise
- The NTCIP adapter reads real phase bitmaps from the emulator and observes the
  dual-ring sequence advancing through both barrier groups
- Phase holds are acknowledged and read back from the controller
- Emergency preemption is validated by the Safety Engine and records the verdict
- Grounded Copilot response verification
- The database schema is at migration head

Phase 2 (backend intelligence):
- The event bus rejects undeclared topics and drops the *oldest* event under
  backpressure, counting the loss
- An unprobed provider is `UNKNOWN`, not healthy; hysteresis degrades fast and
  recovers slowly; circuit breakers reopen with a longer cooldown after a
  failed probe
- A detector that never reported is `INSUFFICIENT_DATA`, not an alarm
- An unconfigured delivery channel records `SKIPPED_NOT_CONFIGURED`
- Repeated matches fold into one alert with an occurrence count
- Throughput refuses counts with no recorded observation window
- Webster refuses over-capacity and thin-data cases, and returns a full trace
- A scenario writes to no observed-data table and refuses an absent baseline
- The Copilot refuses an unknown junction and cites every claim
- SLA targets are copied at creation; evidence must reference a real record
- The audit chain verifies, and detects both modification and deletion
- An API key cannot hold `signal:command` and is stored hashed
- Import dry runs write nothing and report every rejection by row number
- No traffic measurement is exported to Prometheus
- The WebSocket gateway refuses unauthenticated handshakes

Phase 3 (operator insight):
- A junction with nothing attached is `UNRATED` with `score: null` — never 0
- Missing equipment is excluded from the weighted mean, not scored zero
- The network roll-up excludes unrated junctions from its mean
- The optimiser's trust gate blocks measured demand but never operator-entered
  volumes, and never preempts a structural lane-mapping refusal
- Welch's test returns `NO_MEASURABLE_CHANGE` when the interval contains zero,
  and `IMPROVED` only when the whole interval excludes it
- Direction awareness: rising delay degrades, rising speed improves
- Fewer than 8 samples per side yields no verdict and no interval
- Verifying a Safety-Engine-rejected command is `NOT_APPLICABLE`
- Stringline refuses a progression speed from a sub-resolution offset
- A corridor of fewer than two junctions is `NOT_COMPUTABLE`
- Handover preview stores nothing; blind spots are listed with their reasons
- A junction polled all shift but with no detectors is `PARTIAL`, not unseen
- Editing never alters the generated snapshot; sign-off freezes the record
  (409 on edit); a draft cannot be acknowledged

Phase 4 (production readiness):
- Liveness touches no dependency; readiness 503s naming the failing check
- Probes need no auth and leak no junction names, counts or phase state
- A second instance does not poll while the first heartbeats; an expired lease
  is taken over; a non-holder reports `NOT_LEADER` rather than looking idle
- Renewing a lease does not reset its acquisition time
- Production refuses localhost CORS, wildcard CORS, `DEBUG=true` and the
  placeholder `SECRET_KEY`; development still needs no configuration
- The suite runs identically on SQLite and PostgreSQL
- Bootstrapping an admin refuses an absent, published or short password in
  production, never overwrites an existing account, and still needs no
  configuration locally

### Frontend render check

```bash
cd frontend
npm run check:render
```

64 assertions that render the Phase 3 components to HTML and check the
truthfulness invariants survive into the markup an operator actually sees.
`tsc -b` and `vite build` prove none of this — a component can compile and
bundle cleanly and still render a confident `0` where the API returned `null`.

It adds no test-runner dependency: `react-dom/server` is already installed, so
the check bundles with the existing Vite toolchain and runs under Node. Its
fixtures are recorded API responses from a backend polling three emulated NTCIP
controllers, never invented payloads; see
`frontend/scripts/render-check/README.md` for their provenance.

Among other things it asserts that an `UNRATED` junction renders a dash rather
than a zero, that stringline observation gaps are painted with the hatch and
never a colour, that a progression line is drawn only for segments the backend
computed a speed for, and that a confidence interval containing zero renders as
`NO MEASURABLE CHANGE`.

---

## 5. Running the Application

### Start Backend API Server
```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Start Frontend Application
```bash
cd frontend
npm run dev
```

The application will be accessible at:
- **Web Console**: `http://127.0.0.1:5173`
- **REST API Docs**: `http://127.0.0.1:8000/docs`
- **Default Operator**: `admin` / `TrafficIntel2026!`


---

## 6. Operations Console API

Endpoints backing the interactive console. All require a bearer token.

| Endpoint | Purpose | Truthful empty state |
|---|---|---|
| `GET /api/v1/map` | Layered map features (junctions, incidents, cameras, sensors, weather, transit), each with a provenance envelope | Per layer: `NO_CAMERA_CONNECTED`, `NO_SENSOR_DATA_AVAILABLE`, `WEATHER_DATA_UNAVAILABLE`, `TRANSIT_FEED_NOT_CONFIGURED`, … |
| `GET /api/v1/timeline/{id}` | Merged junction event feed: incidents, signal commands, preemptions, audit entries | `NO_RECORDED_EVENTS_IN_WINDOW` |
| `GET /api/v1/timeline/{id}/replay` | Stored telemetry for the time scrubber | `NO_STORED_TELEMETRY_FOR_THIS_WINDOW` / `INSUFFICIENT_SAMPLES_FOR_REPLAY` |
| `POST /api/v1/signals/commands/validate` | Dry run through the Safety Engine. Writes nothing, does not consume the idempotency key | n/a — always returns a full per-rule verdict |

**Console routes added in Phase 3.** `/data-trust` (trust score and change
verification), `/stringline` (corridor time-space diagram), `/handover` (shift
handover). The junction drawer now leads with the junction's trust banner.

**Junction quality roll-up.** A junction's marker colour comes from the *worst*
state among its configured sources, never the freshest or an average. A live
controller heartbeat must not paint a junction green while the detectors
feeding every traffic number on screen have gone silent. `quality_basis` names
the sources the verdict rests on.

**Replay never interpolates.** The endpoint returns the samples that exist and
reports `interpolation: NONE_GAPS_ARE_PRESERVED`. A sensor outage shows as a
gap in the track, labelled with its duration, not a line drawn through it.

---

## 7. Backend Intelligence API

| Endpoint | Purpose | Truthful refusal |
|---|---|---|
| `GET /api/v1/health/providers` | Measured provider health with hysteresis and circuit state | `UNKNOWN` before any probe; `NO_PROVIDER_HAS_BEEN_CONTACTED_YET` |
| `GET /api/v1/health/stream` | Event bus and gateway stats, including dropped-event counts | — |
| `GET /api/v1/health/poller` | NTCIP polling status and last cycle | Lists skipped controllers with the reason |
| `POST /api/v1/rules/{id}/evaluate?dry_run=true` | Evaluate a rule, writing nothing | `INSUFFICIENT_DATA` per subject |
| `GET /api/v1/analytics/performance/{id}` | Full ATSPM report | `INSUFFICIENT_DATA` (n / n-required) vs `NOT_COMPUTABLE` (missing input) |
| `POST /api/v1/optimizer/recommend` | Webster/HCM proposal + Safety Engine verdict | `DEMAND_AT_OR_ABOVE_CAPACITY`, `INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST` |
| `POST /api/v1/scenario/run` | Hypothetical timing scenario | Baseline comparison refused without enough real samples |
| `POST /api/v1/copilot/ask` | Grounded tool-calling Copilot | `NO_SUPPORTING_RECORDS` with no fabricated figure |
| `GET /api/v1/incidents/{id}/report` | Post-incident report | Lists its own gaps |
| `GET /api/v1/governance/audit/verify` | Hash-chain verification | `BROKEN` with the break type and sequence |
| `POST /api/v1/ingest/{format}?commit=false` | Validate an import without writing | Every rejected row with its number and reason |
| `GET /api/v1/reports/*?format=pdf\|csv\|json` | Operational reports | Insufficiency stated, never omitted |
| `GET /api/v1/trust/{id}` | Data-quality trust score with per-component breakdown | `UNRATED` with `score: null` — never 0 |
| `GET /api/v1/trust/network` | Network roll-up | Mean is over rated junctions only; unrated excluded, not zeroed |
| `GET /api/v1/verification/command/{id}` | Did that command measurably help? | `NO_MEASURABLE_CHANGE`, `INSUFFICIENT_DATA`, `NOT_APPLICABLE` |
| `GET /api/v1/verification/window/{id}` | Compare around any operator-nominated moment | Same; settle period excluded from both sides |
| `GET /api/v1/stringline/{corridor_id}` | Time-space diagram from observed state | Gaps preserved; `OFFSET_BELOW_MEASUREMENT_RESOLUTION` |
| `GET /api/v1/handover/preview` | Shift snapshot without creating a record | Blind spots listed with the reason each junction was unseen |
| `POST /api/v1/handover/{id}/sign-off` | Freeze the handover | 409 on any later edit |

**The distinction that runs through all of it.** `INSUFFICIENT_DATA` means the
right inputs exist but there are too few — wait, or widen the window.
`NOT_COMPUTABLE` means a required input does not exist at all — connect
something; waiting will not help. Collapsing the two into a dash is how a
dashboard ends up reassuring an operator about a junction nobody is measuring.

**WebSocket.** `/api/v1/ws?token=<jwt>` is authenticated and supports
per-client topic subscriptions. Send `{"action":"subscribe","topics":["signal.*"]}`.
The gateway reports dropped events to the client when it falls behind, and the
console shows that gap in its status strip: a stream gap nobody can see is
worse than one they can.

**Prometheus.** `/metrics` exports platform metrics only. No vehicle counts, no
occupancy, no speeds — a scrape strips source, timestamp and quality state, and
a gauge reading `occupancy_pct 42` says nothing about whether that detector
reported four seconds or forty minutes ago.

---

## 7a. Interface States for Every Feature

Each feature declares three states explicitly, because the failure this
platform exists to prevent is an interface that looks the same whether it has
data or not. The distinction that matters throughout: **an empty state says
what is missing and why**, never just a dash or a blank panel.

| Feature | Loading | Empty (truthful) | Error |
|---|---|---|---|
| **Trust score** (`/data-trust`) | Skeleton rows; no numbers, no partial score | No junctions → `NO JUNCTIONS CONFIGURED` with a link to setup. Junction present but unmeasured → band `UNRATED`, score renders `--`, with the on-screen reason that zero would mean "measured and bad" | `TRUST ROLL-UP UNAVAILABLE` + the failure text + Retry. No stale figure is left on screen pretending to be current |
| **Trust component** | Inherits the panel skeleton | `NOT_CONFIGURED` / `NOT_APPLICABLE` with a hatched bar rather than an empty track — an empty track reads as zero at a glance | Component omitted from the mean, never scored 0 |
| **AI gate** | n/a — derived from the score | Gate closed with the limiting factor named, plus the remedy: enter volumes directly | Gate closed (fails safe); refusal reason shown |
| **Change verification** (`/data-trust`) | Skeleton while comparing | No run yet → prompt explaining what will be compared. No telemetry → `INSUFFICIENT_DATA` with "this is not evidence the change had no effect". No executed commands → explains that Safety-Engine-rejected commands never reached hardware | Named failure inline beside the form; no verdict is rendered |
| **Verification verdict** | n/a | `NO_MEASURABLE_CHANGE` is a **result**, not an empty state — rendered with the interval spanning zero | Thin samples → no interval drawn at all |
| **Stringline** (`/stringline`) | Skeleton; no axes drawn | No corridors → `NO CORRIDORS CONFIGURED` + link. Fewer than two junctions → `NOT_COMPUTABLE`. No polled state → `INSUFFICIENT_DATA`, and **the diagram is not drawn rather than drawn empty**, because empty axes read as "no green was displayed" | `STRINGLINE UNAVAILABLE` + Retry; nothing is drawn |
| **Stringline gaps** | n/a | Hatched texture, never a colour, so absence can never be mistaken for a state | n/a |
| **Progression speed** | n/a | `OFFSET_BELOW_MEASUREMENT_RESOLUTION` / `IMPLIED_SPEED_IMPLAUSIBLE`, stated in words, with no line drawn on the diagram | n/a |
| **Shift handover** (`/handover`) | Skeleton rows in the list | No handovers → explains what one captures. No pending actions → "nothing outstanding was detected". No blind spots → "every junction reported on every channel" | Named failure banner; the record is never partially saved |
| **Handover snapshot** | n/a — fixed at creation | Absent → `NO SNAPSHOT RECORDED`. Null trust mean → `--`, never `0.0` | Read-only; cannot fail independently of the record |

All of these are asserted by `npm run check:render` rather than only described
here.

---

## 8. How to Demo This Truthfully

The hard part of demonstrating this platform is that a clean installation
honestly has nothing to show. That is the product working. This section shows a
reviewer how to connect a source that speaks a real protocol, so the console
fills with state that was genuinely read off a wire — and shows which panels
stay empty, and why.

### 8.1 The rule this emulator obeys

An emulator that speaks a protocol is a legitimate integration target. An
emulator that invents traffic numbers is fabricated data wearing a costume.

`backend/tools/ntcip_emulator.py` is the first kind. It is a UDP SNMPv1 agent
implementing the NTCIP 1202 phase status and phase control objects, driven by a
real NEMA dual-ring barrier sequencer with genuine minimum green, yellow change
and all-red clearance intervals. It serves **signal state only**. It reports no
vehicle counts, no occupancies, no speeds and no detector actuations, so
`phaseStatusGroupVehCalls` and `phaseStatusGroupPedCalls` read zero — a truthful
"no call registered", not invented demand.

**Consequence, and it is the point:** with only the emulator connected, the
signal panels come alive while every traffic-measurement panel correctly shows
`NO SENSOR DATA AVAILABLE` and analytics shows `NO_HISTORICAL_DATA_AVAILABLE`.
A reviewer should expect that, and should be suspicious of any build where
connecting a signal controller alone makes traffic charts appear.

### 8.2 Run the emulator

```bash
cd backend
python -m tools.ntcip_emulator --host 127.0.0.1 --port 1610
```

It prints its live interval, green phases and any active hold every two seconds:

```
NTCIP 1202 emulator on 127.0.0.1:1610
Reports signal phase state only. No vehicle counts, no detector calls.
  GREEN          green=2,6    yellow=-        held=-
  YELLOW         green=-      yellow=2,6      held=-
  GREEN          green=4,8    yellow=-        held=-
```

### 8.3 Register it as a controller

With the API running and an intersection created, register a controller whose
protocol is `NTCIP_1202` pointing at the emulator's port, then run the
connection test (Settings → Hardware Wizards, or directly):

```bash
# Replace <TOKEN> and <INTERSECTION_ID>
curl -X POST http://127.0.0.1:8000/api/v1/signals/controllers \
  -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -d '{
        "intersection_id": "<INTERSECTION_ID>",
        "name": "Emulated Cabinet 1",
        "vendor": "Emulator", "model": "NTCIP-1202", "protocol": "NTCIP_1202",
        "ip_address": "127.0.0.1", "port": 1610, "cycle_length": 90,
        "phases": [
          {"phase_number": 2, "ring": 1, "barrier": 1, "name": "NB Thru", "conflicting_phases": [4, 8]},
          {"phase_number": 4, "ring": 1, "barrier": 2, "name": "EB Thru", "conflicting_phases": [2, 6]},
          {"phase_number": 6, "ring": 2, "barrier": 1, "name": "SB Thru", "conflicting_phases": [4, 8]},
          {"phase_number": 8, "ring": 2, "barrier": 2, "name": "WB Thru", "conflicting_phases": [2, 6]}
        ]
      }'

curl -X POST http://127.0.0.1:8000/api/v1/signals/controllers/<CONTROLLER_ID>/test-connection \
  -H "Authorization: Bearer <TOKEN>"
```

A successful test returns `"connection_status": "CONNECTED"` **and**
`"state_readable": true` with the phases the emulator is actually displaying.

### 8.4 What a reviewer should check

1. **Reachability is not readability.** Register a second controller with
   protocol `ASC3_ETHERNET` pointing at any open TCP port. Its status becomes
   `REACHABLE`, its phase reads `null` with reason
   `UNREADABLE_NO_PROTOCOL_SESSION`, and `POST /api/v1/signals/commands`
   against it is **rejected by the Safety Engine** with an explanation. No
   phase number is ever invented for it.

2. **Commands record what the hardware did, not what was asked.** Issue a phase
   hold against the emulated controller. The response carries
   `response_payload.post_command_state.effect_verification`, which is
   `OBSERVED_PHASE_DISPLAYING_GREEN` only when a read-back confirmed it, and
   `ACCEPTED_BY_CONTROLLER_NOT_YET_DISPLAYING` when the hold was accepted for a
   phase that is not currently green. Both are truthful; neither is a claim the
   requested phase is live.

3. **Stop the emulator mid-session.** The controller transitions to
   `DISCONNECTED`, and its `active_phase` is cleared rather than freezing at
   the last value it showed.

4. **Preemption cannot buy permission.** Request preemption for a phase that
   conflicts with the active phase. It is recorded as `REJECTED` with the
   Safety Engine's violations listed in the console.

5. **Empty states stay empty.** Traffic, analytics, predictions and corridor
   bandwidth remain in their truthful empty states throughout, because no
   traffic was ever measured.

6. **An unwatched junction is UNRATED, not zero.** Open `/data-trust` on a
   clean installation. Every junction shows `--` and band `UNRATED`, the
   network mean is withheld, and the page says in words that unrated junctions
   were excluded from the mean rather than counted as zero. Attach the
   emulator and the junction becomes rated as its components come online — the
   components list shows exactly which ones, and which is the limiting factor.

7. **The AI gate blocks measured demand but not your own numbers.** With a
   junction below the threshold, `POST /api/v1/optimizer/recommend` with just
   an `intersection_id` is refused with `TRUST_SCORE_BELOW_AI_GATE`. The same
   request with `movements` you typed in computes normally, and says so. A
   junction with no lane-to-phase mapping is told about the mapping first.

8. **Run two emulators on one corridor and read the stringline.** Both report
   real signal state, so `/stringline` draws observed green bands. Kill one for
   thirty seconds: the gap is hatched, not drawn through, and the band either
   side is not joined across it. Because the emulators free-run rather than
   coordinate, the progression segment reports
   `OFFSET_BELOW_MEASUREMENT_RESOLUTION` or an implausible-speed refusal rather
   than printing a green-wave speed — dividing 400 m by an unmeasurable offset
   is arithmetic, not a measurement.

9. **Verification refuses to flatter you.** Use `/data-trust` → Change
   Verification on a window where nothing changed. The confidence interval
   straddles the marked zero line and the verdict is `NO_MEASURABLE_CHANGE`,
   not a small improvement. On a junction with no telemetry it is
   `INSUFFICIENT_DATA`, with the explicit note that this is not evidence the
   change had no effect.

10. **A handover freezes when signed.** Create one at `/handover`. The
    coverage-gaps section separates junctions that went unseen entirely from
    those observed on some channels but not others, and names which channels
    did report. Edit
    the notes, sign off, then try to edit again: 409, with the reason that the
    next shift may already have acted on it.

### 8.5 Connecting a real camera (RTSP)

Point a camera at the console and run the camera connection test. A successful
TCP handshake marks the camera `REACHABLE` with `fps` and `resolution` **null**
and `measurement_status: NOT_MEASURED_NO_RTSP_SESSION`, because a handshake
negotiates no stream. A camera becomes `CONNECTED` only after an edge unit
posts real detections to `POST /api/v1/cameras/{id}/diagnostic-ingest`.

---

## 9. Production Deployment

Everything in this section was executed against real containers, not written
from memory. Three defects were found by running it and are documented in §9.6,
because a deployment guide nobody has followed is a guess.

### 9.1 Bring the stack up

```bash
cp .env.example .env          # then edit: see below
docker compose up -d
```

- **Console** — `http://localhost:8080`
- **API** — `http://localhost:8080/api/v1` (proxied through the console)

Four services: `db` (PostgreSQL 16 + PostGIS 3.4), `migrate` (runs to
completion and exits), `backend`, `console` (nginx serving the bundle and
proxying the API).

The API port is **not** published to the host. Everything reaches it through
nginx, which gives one origin, no CORS, and one place to terminate TLS.

Required in `.env`:

| Variable | Why |
|---|---|
| `POSTGRES_PASSWORD` | Compose refuses to start without it rather than inventing a default |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` — the app refuses to boot in production on the published placeholder |
| `ENVIRONMENT` | `production` enables the guards in §9.4 |
| `BACKEND_CORS_ORIGINS` | **Leave empty** for this topology — see §9.4 |

### 9.1a Create the first operator

A fresh deployment has **no users**. Creating one is an explicit step, not a
side effect of a container booting — because an account provisioned
automatically is an account whose password nobody chose:

```bash
docker compose exec -e INITIAL_ADMIN_PASSWORD='<a password you chose>'     backend python -m app.bootstrap_admin
```

With `ENVIRONMENT=production` this **refuses** to run if the password is
absent, is the published development password, or is shorter than 12
characters. This account can command signal controllers, so a password that
appears in this repository is the same defect as the placeholder `SECRET_KEY` —
and a worse one, because it grants `signal:command` rather than merely forging
tokens.

Locally (`ENVIRONMENT=development`) it falls back to the documented default
with a loud warning, so local setup still needs no configuration.

Re-running it never overwrites an existing account: rotating a forgotten
password is a deliberate act, not something a re-run of setup does silently to
a live system.

### 9.2 Migrations are a separate service, deliberately

`migrate` runs `alembic upgrade head` and exits; `backend` waits for it via
`service_completed_successfully`.

Migrations are **not** run from the API's entrypoint. If they were, two
replicas starting together would race each other through the same migration,
and the loser's failure would surface as a crash-looping container rather than
as a failed deploy. It also means a migration that fails stops the release
instead of taking the API down with it.

Both dialects are exercised by CI:

```bash
# SQLite (default, needs nothing installed)
cd backend && python -m pytest

# PostgreSQL — the identical suite
TRAFFICINTEL_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/scratch \
    python -m pytest
```

Run both. "Dual-dialect" was an untested claim until it was executed, and
PostgreSQL rejected a boolean column default that SQLite had accepted for
months (§9.6).

### 9.3 Scaling: exactly one instance polls

**The controller poller runs in-process.** Two API replicas would both poll
every controller and write two `signal_state_logs` rows per observation,
silently doubling every throughput, arrival-on-green and split-failure figure
derived from that log.

That is worse than an outage. An outage is visible; a doubled measurement just
looks like a busy junction, and an operator would act on it.

So polling is leader-elected through a lease row (`poller_leases`, migration
`0010`). Scaling is safe:

```bash
docker compose up -d --scale backend=3
```

- Exactly one replica holds the lease and polls; it renews on every cycle.
- A replica that does not hold it reports `NOT_LEADER` in
  `GET /api/v1/health/poller` — **not** idle-looking silence. "Another
  instance is doing this" and "polling is broken" must not look the same on a
  status page.
- On clean shutdown the lease is released, so a rolling restart hands over in
  seconds.
- After an unclean kill, a peer takes over once the lease expires
  (`LEASE_TTL_SEC = 30`). Measured at ~34 s in the run documented below.

Inspect it at any time:

```sql
SELECT name, holder_id, heartbeat_at FROM poller_leases;
```

### 9.4 Production configuration guards

With `ENVIRONMENT=production` the application **refuses to start** rather than
running in a state that would mislead an operator:

| Refusal | Why |
|---|---|
| `SECRET_KEY` is the published placeholder | It is in this repository, so every issued token is forgeable |
| `BACKEND_CORS_ORIGINS` contains `localhost`/`127.0.0.1` | A stale dev default lets a page on a developer's machine make credentialed requests against the live network — and nothing in the UI would reveal it |
| `BACKEND_CORS_ORIGINS` is `*` | Browsers reject a wildcard on credentialed requests, so it fails at runtime as well as being unsafe |
| `DEBUG=true` | Debug responses expose tracebacks and internal paths |
| Schema is not at head | An instance serving a drifted schema fails *inside requests, mid-shift*, as wrong or missing data |

**Set `BACKEND_CORS_ORIGINS` empty in this topology.** The console and API
share one origin through nginx, so browser requests are same-origin and CORS is
never consulted. An empty allow-list costs nothing and grants no cross-origin
access at all.

`BACKEND_CORS_ORIGINS` accepts a JSON array *or* a plain comma-separated
string, because deployment tooling supplies environment variables as strings.

### 9.5 Probes

| Endpoint | Purpose | Behaviour |
|---|---|---|
| `GET /api/v1/health/live` | Liveness | Touches **nothing external**. A liveness probe that checks the database restarts a healthy application every time the database hiccups, turning a brief blip into a restart storm that takes the console down for the whole shift. |
| `GET /api/v1/health/ready` | Readiness | 503 with the failing check named. Verified: with the database stopped, liveness stayed 200 while readiness returned 503 reporting `database_reachable=false` and `schema_at_head` as *"Not checked: the database did not answer"* — not a false drift claim. |

Both are unauthenticated: a probe runs before anyone has a token, and a
readiness endpoint that returns 401 to its own orchestrator is
indistinguishable from one that is down. They therefore expose no operational
detail — no junction names, no counts, no phase state — and a test asserts it.

Readiness is about **this instance**, not the field. A controller being
unreachable is reported per device; it never takes the console out of rotation,
because operators need the console most when equipment is failing.

### 9.6 Defects found by actually running this

**1. PostgreSQL rejected a boolean column default.** Five migrations used
`server_default=sa.text("0")`, which SQLite accepts and PostgreSQL refuses
(`column "escalated" is of type boolean but default expression is of type
integer`). The platform had never been run on its own documented production
database. Fixed with `sa.false()`/`sa.true()`, which render correctly on both;
all 10 migrations now apply and round-trip on both dialects, and the full suite
passes on both.

**2. nginx pinned the API's address at startup.** With the API in an `upstream`
block, nginx resolved the hostname once at config load and cached it. Killing
an API replica made the console return **504 forever** — a total outage caused
by an ordinary redeploy, recoverable only by reloading nginx. Fixed by
resolving through a variable with Docker's embedded DNS; verified by recreating
the backend container and confirming the console follows it.

**3. Comma-separated env vars never reached their validator.** pydantic-settings
JSON-parses complex fields from the environment *before* validators run, so
`BACKEND_CORS_ORIGINS=http://localhost:8080` failed with an unreadable parse
error at import time. Fixed with `NoDecode` plus explicit parsing of both
accepted forms.

### 9.7 Backup and restore

The database is the entire operational record — telemetry, the hash-chained
audit ledger, signed-off handovers. The container volume is not a backup.

```bash
# Backup
docker compose exec -T db pg_dump -U trafficintel -Fc trafficintel > backup.dump

# Restore into an empty database
docker compose exec -T db pg_restore -U trafficintel -d trafficintel --clean backup.dump
```

After restoring, verify the audit chain before trusting the record:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/v1/governance/audit/verify
```

A restore that silently truncated the ledger would otherwise look identical to
a clean one. The chain reports `BROKEN` with the break type and sequence
number.

### 9.8 What this deployment does not yet include

Stated plainly rather than left to be discovered:

- **No TLS.** nginx serves plain HTTP on 8080. Terminate TLS at an ingress or
  add a certificate to the console service before exposing it.
- **No log shipping or metrics scraping configured.** The application emits
  structured JSON logs and exposes Prometheus metrics at `/metrics`; nothing
  collects them here.
- **No automated backups.** §9.7 is manual.
- **Single database instance.** No replica, no automated failover.
- **`--workers 1`** on uvicorn. Raising it forks the poller into every worker;
  the lease makes that safe but wasteful. Scale replicas instead.
