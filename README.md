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

All 254 tests validate deterministic safety, data quality transitions, protocol
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

Grounded intelligence:
- Student-t p-values match published tables; anomaly confidence is 1 − p
- A metric never recorded is `NOT_COMPUTABLE`; a baseline under 30 samples is
  `INSUFFICIENT_DATA` however extreme the reading; nothing recent is
  `INSUFFICIENT_DATA`, not normal
- A clear spike is flagged and names the `traffic_metrics` row it came from;
  ordinary variation is not flagged
- The same deviation earns lower confidence from a smaller baseline
- Bonferroni: a 1-in-300 reading is flagged alone but not among fifteen
- A constant baseline is `NOT_COMPUTABLE`; a CUSUM alarm counts only once
  Welch confirms it, and is only *suspected* with too few readings
- The time-of-day baseline is centred on the window under test
- Forecasts refuse short, gapped and stale history; a random walk is refused
  with `NO_SKILL_OVER_PERSISTENCE` and the fitted model in the response; a
  predictable series gets labelled points inside their intervals
- Fusion: two corroborating sources → probable incident naming both; one
  detector with both symptoms → uncorroborated; one symptom → partial; a
  statistically real but small change is not a symptom; lane-less sources are
  unattributed; a silent configured sensor is `INSUFFICIENT_DATA`
- Evaluating writes nothing; recording creates `DETECTED` only, with evidence
  rows that resolve to stored observations, never a duplicate open incident,
  and requires `incident:write` (viewers and auditors get 403)
- No intelligence endpoint creates a signal command

Corridor and network scale:
- Only the dispatcher calls an adapter to change a controller (static scan of `app/`)
- Timing plans: barrier misalignment, ring sums, short splits, pedestrian
  intervals, unserved phases, concurrent conflicts, unreadable or non-NTCIP
  controllers and out-of-range offsets are each rejected by the Safety Engine
- The emulator runs a pattern with green starting at the offset, refuses to run
  an inconsistent one, and applies an SNMP SetRequest atomically
- An acknowledged plan the controller does not run is not a read-back match
- Coordination: fewer than two coordinatable controllers is `NOT_COMPUTABLE`;
  offsets follow travel time; the critical junction sets the cycle; a cycle
  below the pedestrian minimum is refused; design speed is never assumed
- Applying writes and reads back each controller; a state change since the
  proposal blocks the whole plan; a controller that stops answering leaves it
  `PARTIALLY_APPLIED`; applying needs `signal:configure`
- Verification confirms offsets the stringline observes and reports divergence
- Manual preemption now reaches the controller; an unacknowledged call is
  `FAILED` and audited `FAILED`, never `EXECUTED`
- AVL: an approaching ambulance preempts its approach's phase; conflicts are
  rejected with nothing sent; stale, corrupted, fixless, heading-away,
  unauthorised and unmapped cases are refused; no double preemption within the
  rearm window; position reports are not throttled at the command rate
- TSP: dry runs write nothing; a late bus on green gets an extension through
  the dispatcher; on-time, early and unknown-lateness buses do not; a bus on red
  is not given a useless hold; stale signal state means no request; lockout;
  the Safety Engine still decides; dispatch needs `signal:command`

### Frontend render check

```bash
cd frontend
npm run check:render
```

134 assertions that render the Phase 3, grounded-intelligence and corridor-scale components to HTML and check the
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
handover). Grounded intelligence adds `/intelligence` (anomalies, forecast,
incident fusion). The junction drawer now leads with the junction's trust banner.

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
| **Anomalies** (`/intelligence`) | Skeleton rows; no status word, no number | Per metric: `NOT COMPUTABLE` / `INSUFFICIENT DATA` with the reason code and explanation. Every unevaluated metric is listed under **NOT EVALUATED** with "no flag is not evidence of normal conditions". Confidence is capped at `>99.99%`, never rounded to 100% | `ANALYSIS UNAVAILABLE` + Retry; the previous result is cleared |
| **Forecast** (`/intelligence`, `/predictions`) | Skeleton while fitting and backtesting | `NOT COMPUTABLE` draws no chart. A refusal draws observed bins only, states that no forecast line is drawn, and — when a model was fitted — shows it under "A MODEL WAS FITTED AND MEASURED" with its MAE beside persistence's | Named failure; no stale forecast left on screen |
| **Forecast line** | n/a | Observed bins solid and labelled `MEASURED`; forecast dashed inside its 95% band, after a divider, stamped `SCENARIO / HYPOTHETICAL` | n/a |
| **Incident fusion** (`/intelligence`) | Skeleton rows | No approaches → "NO SEGMENTS CONFIGURED". Single-sensor segment → `FEWER_THAN_TWO_INDEPENDENT_SOURCES`. Lane-less sources listed under **UNATTRIBUTED SOURCES** | Record failure is shown inline; a 403 says the role lacks `incident:write`, and nothing was filed |
| **Coordination plan** (`/coordination`) | Skeleton while computing and validating | No corridors → `NO CORRIDORS CONFIGURED`. An uncoordinatable corridor renders `NOT COMPUTABLE` with every junction's reason. A refused proposal names the refusal (e.g. `CYCLE_BELOW_MINIMUM_FEASIBLE`) | Named failure. A 403 on apply names `signal:configure` and states that nothing was sent |
| **Planned diagram** | n/a | Drawn in dashed outline and labelled `PLANNED ... (NOT OBSERVED)`. It is never presented as what the controllers are doing | n/a |
| **Plan verification** | n/a | `INSUFFICIENT DATA` until the stringline has seen enough cycles. This is stated as "not a failure" | Named failure |
| **Transit priority** (`/transit`) | Skeleton while fetching and evaluating | No feed → `TRANSIT FEED NOT CONFIGURED`, and no bus is simulated. Every bus the feed contains is listed with its decision. Unknown lateness renders `UNKNOWN`, never `0s` | Named failure. A 403 on dispatch names `signal:command` |
| **Preemption verdict** (`/emergency`) | n/a | `ACTIVE` only when the controller acknowledged. `FAILED` says "no preemption is in effect". `REJECTED` says "nothing was sent" | Request error is shown inline |

All of these are asserted by `npm run check:render` rather than only described
here.

---

## 7b. Grounded Intelligence

Three capabilities, each computed only from telemetry the platform stored, and
each with a specific way of producing a confident-looking number from nothing
that it refuses to do. Console route: `/intelligence`; the forecast also
renders on `/predictions`.

No schema change: anomalies and forecasts are computed on read, and fusion
detections use the existing `incidents` and `incident_evidence` tables. No
migration was added.

| Endpoint | Purpose | Refusal / empty states |
|---|---|---|
| `GET /api/v1/intelligence/anomalies/{id}` | Point and sustained-shift anomalies in stored throughput, occupancy and speed | Per metric: `NOT_COMPUTABLE` (`NO_STORED_VALUES_FOR_METRIC`, `BASELINE_HAS_ZERO_VARIANCE`) · `INSUFFICIENT_DATA` (`NO_SAMPLES_IN_TEST_WINDOW`, `BASELINE_TOO_SMALL`) |
| `GET /api/v1/predictions/forecast/{id}` | ARIMA(p,d,0) short-horizon forecast with 95% intervals | `NOT_COMPUTABLE` (`NO_STORED_VALUES_FOR_METRIC`) · `INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST` with `INSUFFICIENT_HISTORY`, `GAPS_BREAK_HISTORY`, `LATEST_DATA_TOO_OLD`, `NO_SKILL_OVER_PERSISTENCE`, `SERIES_UNCHANGED_IN_BACKTEST`, `NO_MODEL_COULD_BE_FITTED`, `NO_COMPLETE_BIN` |
| `GET /api/v1/intelligence/incident-fusion/{id}` | Corroborated occupancy-spike + speed-drop per approach. Writes nothing | Per segment: `NOT_COMPUTABLE` (`FEWER_THAN_TWO_INDEPENDENT_SOURCES`) · `INSUFFICIENT_DATA` (`CONFIGURED_SOURCES_SILENT`, `TOO_FEW_SAMPLES_PER_SOURCE`) · `UNCORROBORATED_SINGLE_SOURCE` · `PARTIAL_SYMPTOMS` · `NO_INCIDENT_INDICATED` |
| `POST /api/v1/intelligence/incident-fusion/{id}/record` | Files each probable incident as `DETECTED` with the corroborating observations attached as evidence. Requires `incident:write` | Skips a segment that already has an open fusion incident (`OPEN_INCIDENT_ALREADY_EXISTS`) |

All three accept `as_of` to evaluate a past instant.

### Anomaly detection

- **Point anomalies** use a prediction-interval t-test:
  `T = (x - x̄) / (s·√(1 + 1/n))`, Student's t with n−1 degrees of freedom,
  and report confidence as `1 − p`. That is what makes confidence *derived
  from sample size*: the same deviation against a smaller baseline has fewer
  degrees of freedom and a wider interval, so it earns less confidence. The
  p-value is exact (regularized incomplete beta), not a table lookup.
- **Family-wise control.** Every reading in the test window is a separate
  test, so alpha (0.01) is Bonferroni-divided across them. Without it, a quiet
  fifteen-minute window would raise a false flag on roughly one junction in
  seven every quarter hour.
- **Sustained shifts** use a two-sided CUSUM (k=0.5, h=5). An alarm is only a
  suspicion until Welch's test confirms the post-onset readings differ from the
  baseline; with too few post-onset readings it is
  `SUSPECTED_TOO_FEW_SAMPLES_TO_CONFIRM`, never an anomaly.
- **Baseline.** Same time of day (±30 min) on previous days when at least 30
  such readings exist; otherwise the preceding two hours, with a caveat that
  this ignores the daily pattern. Fewer than 30 either way →
  `INSUFFICIENT_DATA`, however extreme the latest reading.
- Every flag names the `traffic_metrics` row it came from.

### Forecasting

- **The model, stated exactly:** ARIMA(p,d,0) — autoregression on the
  d-times-differenced series, fitted by conditional least squares, with **no
  moving-average terms**. The platform carries no statsmodels; a subset of
  ARIMA with an auditable solver is named as that subset everywhere it reports.
- **Order selection by measured error.** Six candidates (p ∈ 1–3, d ∈ 0–1)
  are evaluated by rolling-origin backtest — refit at each of 12 origins on the
  data before it, no look-ahead — and the lowest MAE wins.
- **The refusal has a model behind it.** The winner is compared with naive
  persistence ("next bin equals the last"). Unless it reduces MAE by at least
  10%, the forecast is refused with `NO_SKILL_OVER_PERSISTENCE` — and the
  response carries the fitted model and its measured error. Previously the
  refusal fired on a row count and "enough rows" led to
  `NO_FORECAST_MODEL_REGISTERED`; that status no longer exists.
- **Gaps are never interpolated.** The model trains on the longest gap-free
  run ending at the latest complete bin. The in-progress bin is excluded.
- Every point is stamped `SCENARIO / HYPOTHETICAL`, carries a 95% interval,
  and is clipped to physical bounds (flagged when clipped). The interval's
  **measured** backtest coverage is reported beside it.

### Fusion incident detection

- **Segment** = an Approach — the only segment unit the schema has.
  Observations without a lane are reported as unattributed, never guessed onto
  a segment.
- **Independent source** = a distinct reporting identity. Two identities fed
  by one physical device would be counted twice; the response says so.
- Each source is compared with **its own** baseline (Welch, 95%), and a
  symptom must also clear a practical threshold (occupancy +15 points, speed
  −30%): statistically real but operationally trivial changes do not count.
- **Probable incident** requires both symptoms and at least two independent
  sources showing them. One detector showing both is
  `UNCORROBORATED_SINGLE_SOURCE` — the phantom-incident case.
- The response names the corroborating sources *and* the sources that were
  evaluated and disagreed. `corroboration_ratio` is agreement between sensors,
  not a probability.
- **Recording never verifies.** Incidents enter the lifecycle as `DETECTED`
  with a timeline entry marked `requires_human_verification`.

**Safety invariant.** None of these endpoints can create a signal command; a
test calls all four and asserts the `signal_commands` table is unchanged.

---

## 7c. Corridor and Network Scale

Three capabilities that change what a signal controller does: green-wave
coordination, transit signal priority, and emergency preemption from a vehicle
position feed. Console routes: `/coordination`, `/transit`, `/emergency`.

### The single path to hardware

Every instruction that changes a controller — operator phase holds, manual and
AVL preemption, transit priority, and coordination timing plans — goes through
`app/signals/dispatch.py` (`SignalCommandDispatcher`). The sequence is fixed:

1. Deterministic Safety Engine validation.
2. A `SignalCommand` row, `REJECTED` or `PENDING`, written either way.
3. If rejected: an audit entry, and nothing is sent.
4. Otherwise the adapter is asked, and its acknowledgement recorded.
5. The controller is re-read, and what it *actually* displays is recorded.
6. An audit entry whose result is the real outcome.

A test scans `app/` and fails if anything other than the dispatcher calls an
adapter's `send_command` or `write_timing_plan`.

**Fixed while building this:** the manual preemption endpoint validated calls
and then recorded them `ACTIVE`, audited `EXECUTED`, **without sending anything
to the controller**. Preemption now dispatches. Its status is the real outcome:
`ACTIVE` (the controller acknowledged), `REJECTED` (nothing was sent) or
`FAILED` (validated, but the controller did not acknowledge).

### Endpoints

| Endpoint | Purpose | Refusal / empty states |
|---|---|---|
| `POST /api/v1/coordination/corridors/{id}/propose` | Green-wave plan: common cycle, Webster splits, travel-time offsets, bandwidth in both directions, Safety Engine verdict per controller. Sends nothing. Needs `optimizer:run` | `NOT_COMPUTABLE` (`FEWER_THAN_TWO_COORDINATABLE_CONTROLLERS`, `NO_DESIGN_SPEED`) · `REFUSED` (`CYCLE_BELOW_MINIMUM_FEASIBLE`, `NO_LANE_TO_PHASE_ASSIGNMENTS`, `TRUST_SCORE_BELOW_AI_GATE`, `DEMAND_AT_OR_ABOVE_CAPACITY`, `NO_DEMAND_FOR_BARRIER_GROUP`) · stored as `REJECTED_BY_SAFETY` |
| `POST /api/v1/coordination/plans/{id}/apply` | Re-validates every controller, then writes each part through the dispatcher and reads it back. Needs `signal:configure` | `REJECTED_AT_APPLY` (nothing sent) · `PARTIALLY_APPLIED` (each outcome listed) · `APPLY_FAILED` · 409 if not `PROPOSED` |
| `GET /api/v1/coordination/plans/{id}/verify` | Planned offsets compared with the offsets the stringline **observes** | `OBSERVED_AS_PLANNED` · `DIVERGES_FROM_PLAN` · `INSUFFICIENT_DATA` (not enough cycles yet) · `NOT_APPLICABLE` |
| `POST /api/v1/transit/tsp/evaluate` | Fetches the configured GTFS-Realtime feeds and evaluates conditional TSP. Dry run by default | `TRANSIT_FEED_NOT_CONFIGURED` · `FEED_UNAVAILABLE` · `FEED_UNDECODABLE` |
| `POST /api/v1/transit/tsp/evaluate-feed` | Same, for feed bytes pushed by a gateway (base64 protobuf) | 422 on an undecodable feed |
| `POST /api/v1/emergency/avl` | An emergency vehicle's position (NMEA RMC, or decoded fields) selects the junction and phase, and preempts through the dispatcher. Needs `signal:command` | 422 `CHECKSUM_MISMATCH` / `NO_GPS_FIX` · `POSITION_TOO_OLD` · `VEHICLE_NOT_MOVING` · `NO_JUNCTION_APPROACHED` · `NO_PHASE_SERVES_APPROACH` · `ALREADY_PREEMPTED` · `UNAUTHORIZED_VEHICLE_TYPE` |

### Arterial coordination

- **Only real, readable controllers are coordinated.** A junction qualifies only
  if its controller speaks NTCIP 1202 (the one protocol with a timing-plan
  channel) and is `CONNECTED`. Every other junction is listed with its reason.
- **The Safety Engine gained `validate_timing_plan`.** It checks controller
  readability and capability, cycle bounds and offset range. It checks that
  every configured phase has a split, that splits cover minimum green plus
  clearance and pedestrian walk plus clearance, and that no green exceeds
  maximum green. It checks that **each ring sums to the cycle**, that **both
  rings cross every barrier together**, and that no pair of phases run
  concurrently is configured as conflicting.
- **The common cycle is never below what every junction can physically run.**
  Webster's optimum ignores minimum greens and pedestrian intervals. On the live
  demo corridor it proposed a 40 s cycle, against a 56 s pedestrian minimum, and
  the resulting plan gave the main street 6 s of green. The Safety Engine
  rejected it, so nothing unsafe was applied. The planner now uses the larger of
  the Webster optimum and the minimum feasible cycle, and refuses an
  operator-entered cycle below that floor.
- **Design speed is never measured.** It is either operator-entered or the
  configured speed limit, and it is labelled as such.
- **Bandwidth is reported in both directions.** Optimising one direction usually
  costs the other.
- **Applying is all-or-nothing at the pre-flight check.** Every controller is
  re-validated at apply time. If any would now refuse, nothing is sent to any of
  them: a half-applied green wave moves junctions off their old timing without
  the progression that justified it. After the pre-flight, each write is **read
  back**. A controller whose read-back differs from the plan is recorded as
  `FAILED`, even though it acknowledged the write.
- **NTCIP coordination objects.** Plans are written as one atomic SNMPv1
  SetRequest to `patternTable`/`splitTable` and activated through
  `systemPatternControl`. **Check these OIDs against your controller's MIB
  before field use.** They were written from knowledge of NTCIP 1202 v02's
  coordination section without the standard document to hand, and they are
  exercised only against this project's emulator.
- **Offsets assume the controllers share a time reference** (GPS or NTP). The
  platform cannot check controller clock sync, so `verify` compares the planned
  offsets with what the stringline observes.

**Verified live.** On the three-junction Avinashi Road demo corridor, a 60 s
plan with offsets 0 / 32 / 4 s was applied to three NTCIP emulators through the
real API. After several cycles, `verify` reported `OBSERVED_AS_PLANNED`. The
stringline measured offsets of **31.6 s and 32.6 s** against a planned 32 s,
within the 2 s poll resolution.

### Conditional transit signal priority

A bus gets a green extension only when **all** of the following hold:

- its position is fresh and has a heading;
- it is approaching a junction;
- it is **at least 60 s late**, according to the TripUpdates feed;
- no priority was granted at that junction in the last 180 s;
- a lane on its approach is mapped to a phase;
- that phase is **currently green**, according to polled state no older than 10 s;
- the Safety Engine passes it.

**Unknown lateness is not treated as late.** Every bus evaluated near a
junction is recorded with its decision and reason, whether or not it was
granted priority.

- **Only green extension is requested.** Early green needs NTCIP force-off,
  which the adapter does not implement. A bus arriving on red is recorded as
  `EARLY_GREEN_NOT_SUPPORTED`, rather than being sent a hold that would do
  nothing.
- **GTFS-Realtime decoding is dependency-free** (`app/providers/gtfs_rt.py`).
  It is a protobuf wire-format decoder driven by the published field numbers.
  Unknown fields are skipped, and malformed messages are rejected.
- **There is no demo feed.** A feed that invented buses would put fabricated
  vehicles and lateness into a decision that changes signal timing. Point
  `GTFS_RT_VEHICLE_POSITIONS_URL` / `GTFS_RT_TRIP_UPDATES_URL` at a real agency
  feed, or push real feed bytes to `/transit/tsp/evaluate-feed`.

### Emergency preemption from AVL

- **NMEA RMC is parsed strictly.** The checksum must match, and the receiver
  status must be `A`. A void fix (`V`) is refused, because its coordinates could
  preempt the wrong junction.
- **Targeting is conservative.** A fix older than 10 s is refused. The vehicle
  must be moving at least 5 km/h. The junction must be within 600 m, within 45°
  of the vehicle's heading, and reachable in 40 s or less. The phase comes from
  the lane mapping on the vehicle's approach, never from a guess.
- **The hold covers the vehicle's arrival**: the ETA plus 5 s, bounded by the
  phase's own minimum and maximum green. The same vehicle cannot preempt the
  same junction again within 90 s.
- **AVL position reports have their own rate limit** (600/min per account). The
  signal-command limit (12/min) would cut off an AVL unit reporting at 1 Hz
  after twelve seconds, and the report that should trigger preemption would be
  refused. The commands those reports cause are bounded by the rearm window.
- **The AVL endpoint requires `signal:command`, which API keys can never hold.**
  A CAD/AVL integration therefore authenticates as a dedicated OPERATOR service
  account. That is deliberate: an integration that can trigger preemption can
  change signals.

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

11. **Apply a green wave and watch it be measured.** With the three emulators
    running (§8.2), open `/coordination`, choose the corridor, and enter volumes
    (for example 900 veh/h main street on 2 lanes, 350 cross street) and a
    design speed of 50 km/h. Propose, then apply. Every controller acknowledges
    and reads back the plan. Wait four or five cycles, then press **Verify
    against the stringline**. The observed offsets match the plan to within the
    poll resolution. Before the plan was applied, the same stringline reported
    `OFFSET_BELOW_MEASUREMENT_RESOLUTION` for these free-running controllers.

12. **Watch preemption tell the truth about the controller.** Stop one
    emulator and request manual preemption at its junction. The call passes the
    Safety Engine, and the verdict reads *"the controller did not acknowledge —
    no preemption is in effect"*. It is audited `FAILED`.

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
