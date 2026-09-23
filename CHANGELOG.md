# Changelog

All notable changes to TRAFFICINTEL AI.

## [Unreleased] — Phase 4: Production Readiness

Everything here was executed against real containers and a real PostgreSQL
instance. Three defects surfaced only by running it, and all three would have
shipped silently.

### Added — deployment

- **`docker-compose.yml`** — PostgreSQL 16 + PostGIS 3.4, a one-shot migration
  service, the API, and nginx serving the console and proxying the API. The API
  port is not published: one origin, no CORS, one place for TLS.
- **Backend and console Dockerfiles** — multi-stage, non-root (`uid 10001` /
  `nginx`), with healthchecks. The backend's healthcheck targets *readiness*,
  not liveness, so an instance on a drifted schema is treated as unfit to serve
  rather than merely running.
- **Migrations run as a separate service, never from the API entrypoint.** Two
  replicas starting together would otherwise race through the same migration,
  and the loser's failure would surface as a crash-looping container rather
  than a failed deploy.
- **`.dockerignore`** excludes `*.db`, so a developer's operational database can
  never be baked into an image and arrive in production carrying local records
  that look like real history.

### Added — liveness & readiness probes

- **`GET /health/live`** touches nothing external. A liveness probe that checks
  the database restarts a healthy application every time the database hiccups,
  turning a brief blip into a restart storm.
- **`GET /health/ready`** returns 503 naming the failing check. Verified live:
  with the database stopped, liveness stayed 200 while readiness reported
  `database_reachable=false` and `schema_at_head` as *"Not checked: the database
  did not answer"* — rather than falsely claiming schema drift.
- Both are unauthenticated, because a readiness endpoint that returns 401 to
  its own orchestrator is indistinguishable from one that is down — and both
  are asserted to leak no junction names, counts or phase state.
- Readiness covers **this instance**, never field equipment: a controller being
  unreachable must not take the console out of rotation, because operators need
  the console most when equipment is failing.

### Added — single-writer poll lease (migration `0010_poller_lease`)

- The controller poller runs in-process, so **two API replicas would write two
  `signal_state_logs` rows per observation**, silently doubling every
  throughput, arrival-on-green and split-failure figure derived from that log.
  That is worse than an outage: an outage is visible, while a doubled
  measurement looks like a busy junction and an operator would act on it.
- Polling is now leader-elected through an inspectable lease row with a
  heartbeat. A non-holder reports `NOT_LEADER` rather than appearing idle —
  "another instance is doing this" and "polling is broken" must not look the
  same on a status page.
- The lease is released on clean shutdown so a rolling restart hands over in
  seconds. **Verified end-to-end**: two replicas, one holder with an advancing
  heartbeat and no flapping; after `docker kill` of the holder, the survivor
  took over at ~34 s, consistent with the 30 s TTL.

### Added — explicit administrator provisioning

- **`python -m app.bootstrap_admin`** creates the first operator from
  `INITIAL_ADMIN_PASSWORD`. A fresh deployment previously had no users at all,
  so nobody could log in; the only provisioning path that existed hardcoded the
  published password `TrafficIntel2026!`.
- In production it refuses an absent password, the published development
  password, or anything under 12 characters. This account can command signal
  controllers, so a password printed in this repository is the same defect as
  the placeholder `SECRET_KEY` — and worse, because it grants `signal:command`
  rather than merely forging tokens.
- Deliberately not wired into container startup: an account provisioned as a
  side effect of a container booting is an account whose password nobody chose.
- Re-running never overwrites an existing account, and a clashing email returns
  the reason rather than a SQLAlchemy stack trace.

### Added — production configuration guards

`ENVIRONMENT=production` now refuses to start on: a `localhost` CORS origin, a
wildcard CORS origin, or `DEBUG=true` — alongside the existing placeholder
`SECRET_KEY` and schema-drift refusals. `BACKEND_CORS_ORIGINS` accepts a JSON
array or a plain comma-separated string.

### Added — connection pooling

Bounded pool with `pool_pre_ping`, `pool_recycle` below typical proxy idle
timeouts, a connect timeout, and a server-side `statement_timeout`. Without
`pool_pre_ping` the first request after a database restart or failover fails on
a dead socket *inside an operator's request* rather than at the pool.

### Added — dual-dialect test runs

`TRAFFICINTEL_TEST_DATABASE_URL` runs the identical suite against PostgreSQL.
**154 tests pass on both SQLite and PostgreSQL.**

### Fixed

- **PostgreSQL rejected a boolean column default.** Five migrations used
  `server_default=sa.text("0")` — accepted by SQLite, refused by PostgreSQL
  (`column "escalated" is of type boolean but default expression is of type
  integer`). The platform had never been run against its own documented
  production database. Fixed with `sa.false()`/`sa.true()`; all 10 migrations
  now apply and round-trip on both dialects.
- **nginx pinned the API's address at startup.** With the API in an `upstream`
  block, nginx resolved the hostname once at config load and cached it for the
  process lifetime. Killing an API replica made the console return **504
  indefinitely** — a total console outage produced by an ordinary redeploy,
  recoverable only by reloading nginx. Fixed by resolving through a variable
  with the container DNS resolver; verified by recreating the backend and
  confirming the console follows it.
- **Comma-separated environment values never reached their validator.**
  pydantic-settings JSON-parses complex fields from the environment *before*
  validators run, so `BACKEND_CORS_ORIGINS=http://localhost:8080` failed with an
  unreadable parse error at import time. Fixed with `NoDecode` and explicit
  parsing of both accepted forms.
- **The poll cycle summary had no `status` field**, so a status page could not
  distinguish an idle cycle from a refused one without inferring it.

## [Unreleased] — Phase 3: Operator Insight

Four capabilities aimed at the gap between "the console shows a number" and
"the operator knows what to do about it". Each one is built around a specific
way of producing a confident-looking figure from nothing, and each one refuses
rather than guesses.

### Added — data-quality trust score

- **`app/analytics/trust.py`** scores each junction 0–100 across five weighted
  components (controller readability 0.30, telemetry freshness 0.30, detector
  health 0.20, signal-state coverage 0.10, sample density 0.10), banded
  TRUSTED ≥ 80 / PARTIAL ≥ 60 / UNTRUSTED.
- **UNRATED is not zero.** A junction with fewer than two scorable components
  returns `score: null` and band `UNRATED`. Zero would mean "measured and
  bad"; a junction nobody is watching has not been measured at all, and
  colouring it red would send crews to fix equipment that is working.
- **Weights are renormalised over scorable components only**, so a junction is
  never penalised for a camera it does not have. Missing equipment is reported
  as coverage, not as a low score.
- **The composite is never shown alone.** Every component, its weight, its
  status and its explanation render beside it, with the weakest called out as
  the limiting factor — the thing to actually go and fix.
- **Network roll-up excludes unrated junctions from the mean** rather than
  counting them as zero, which would make an uninstrumented network
  indistinguishable from a failing one.
- **AI gate.** Below a trust score of 60, the optimiser refuses to compute from
  *measured* demand (`TRUST_SCORE_BELOW_AI_GATE`), because a recommendation
  derived from stale detectors carries a confidence its inputs do not support.
  Operator-entered volumes are never gated: a typed volume is the operator's
  own assertion. The gate is applied *after* structural checks, so a junction
  with no lane-to-phase mapping is told about the mapping, not about staleness.

### Added — post-change verification

- **`app/analytics/verification.py`** compares telemetry either side of a
  change using **Welch's t-test** with a 95% confidence interval on the
  difference of means, per metric, with direction awareness (delay down is
  good, speed down is not).
- **The verdict is driven by the interval, not the difference of means.** An
  interval containing zero returns `NO_MEASURABLE_CHANGE` — presented as a
  legitimate answer, not a failure of the analysis. Without this, a 1.2 s drop
  on a metric that swings by 4 s reads as a success, and an operator learns to
  trust noise.
- Fewer than 8 samples per side returns `INSUFFICIENT_DATA` and no interval.
- A **settle period** is excluded from both windows; a controller does not
  change behaviour the instant a command lands, and counting the transition as
  "after" blurs the difference being measured.
- Verifying a command that was **rejected by the Safety Engine** returns
  `NOT_APPLICABLE`: nothing reached the hardware, so there is nothing to
  measure.
- Method caveats (demand is not controlled for, and the comparison is
  observational rather than randomised) travel with the result rather than
  living in a help page.

### Added — corridor stringline (time-space diagram)

- **`app/analytics/stringline.py`** reconstructs green bands per junction from
  `SignalStateLog`, positions junctions by great-circle distance along the
  corridor, and derives progression offsets between adjacent pairs.
- **Bands come from observed state, not from a timing plan.** A plan that says
  "coordinated" and a corridor that is observably not coordinated look
  identical on every other screen.
- **Observation gaps are preserved and hatched, never interpolated across.**
  Connecting the last sample before a gap to the first sample after it would
  invent signal state for the dark period.
- **Band edges are drawn soft**, because a transition is only known to within
  one poll interval; and an interval still green at the window edge gets a
  dashed terminator rather than an end time nobody observed.
- **Sub-resolution offsets do not produce a speed.** An offset at or below the
  observation interval cannot be distinguished from zero, and dividing a real
  distance by it yields an arbitrarily large number that looks like a
  measurement. Reported as `OFFSET_BELOW_MEASUREMENT_RESOLUTION`; a plausibility
  bound (`MAX_PLAUSIBLE_PROGRESSION_KPH = 160`) catches the rest.
- The diagram draws a progression line **only** for segments the backend
  computed a speed for; refused segments are stated in words instead.

### Added — shift handover

- **`app/reporting/handover.py`** generates a machine-collected snapshot of a
  shift — incidents, unacknowledged alerts, provider health, signal command
  activity (including Safety Engine rejections), data coverage, and blind
  spots — and seeds pending actions from real open state.
- **Blind spots are a first-class section**, not a coverage statistic. A quiet
  shift and an unwatched shift look identical on a dashboard, and which one it
  was is precisely what the next operator needs to know.
- **Three parts kept visibly distinct**: the generated snapshot is fixed at
  creation and never editable; operator notes are free text; pending actions
  are seeded automatically but labelled `AUTO_GENERATED` vs `OPERATOR`.
- **Sign-off freezes the record** (409 on any subsequent edit). The next shift
  may already have acted on it, so it is superseded by a new handover rather
  than revised. A draft cannot be acknowledged.
- Migration **`0009_handover`**, round-trips up and down.

### Added — endpoints

`GET /trust/network`, `GET /trust/{id}`, `GET /verification/command/{id}`,
`GET /verification/recent`, `GET /verification/window/{id}`,
`GET /stringline/{corridor_id}`, `GET|POST /handover`,
`GET /handover/preview`, `GET|PATCH /handover/{id}`,
`POST /handover/{id}/sign-off`, `POST /handover/{id}/acknowledge`.

### Added — console

- **`/data-trust`** — network roll-up, junction list sorted worst-first, full
  component breakdown, and the change-verification tool with the confidence
  interval drawn to scale against a marked zero line.
- **`/stringline`** — the SVG time-space diagram with hatched observation gaps,
  soft band edges, and a progression table that names why each refused segment
  was refused.
- **`/handover`** — preview (stores nothing), create, edit notes and actions,
  sign off, acknowledge; the generated snapshot is rendered read-only and
  marked as fixed at creation.
- The **junction drawer now leads with the trust banner**, because how much to
  believe the panels below is the first thing an operator needs, not a
  footnote under them.

### Added — frontend render check

- **`npm run check:render`** renders the Phase 3 components with
  `renderToString` and asserts the truthfulness invariants reach the markup:
  a dash rather than a zero for `UNRATED`, hatched rather than coloured
  observation gaps, no progression line for a refused segment, and
  `NO MEASURABLE CHANGE` for an interval containing zero, and a null
  coverage mean rendering as a dash rather than `0.0`. 64 assertions,
  covering the handover snapshot and every declared empty state.
- **No test-runner dependency was added.** `react-dom/server` is already a
  dependency, so the check bundles with the existing Vite toolchain and runs
  under Node. Fixtures are recorded API responses from a backend polling three
  emulated NTCIP controllers, with their provenance documented beside them.

### Fixed — Phase 3

- **Stringline reported 732,628 km/h** between two junctions whose free-running
  controllers happened to coincide. A sub-poll-interval offset divided into
  400 m produced an absurd figure — and, more dangerously, a slightly larger
  noise offset would have produced a *plausible* one. Now guarded by
  measurement resolution and a physical plausibility bound.
- **The trust gate preempted the structural lane-mapping refusal** in the
  optimiser, telling operators to fix data staleness when the actual problem
  was an unconfigured lane-to-phase assignment. Reordered so structural
  refusals come first.
- **Blind spots conflated "went dark" with "has no detectors".** Found running
  three emulated controllers: junctions being polled successfully all shift
  were filed as blind spots because they had no loops, and the auto-generated
  action then told the next operator that four junctions' "quiet is unknown,
  not clear" — an overstatement for three of them. A section that cries wolf
  erodes exactly the trust it exists to build, and an operator who learns that
  "blind spot" usually means missing detectors will skim past the junction that
  actually stopped reporting. Now split into `TOTAL` (nothing observed at all)
  and `PARTIAL` (some channels reported, others never have), with the channels
  that *did* report named, separate counts, separate pending actions, and
  unseen junctions sorted first.

## [Unreleased] — Phase 2: Backend Intelligence & Reliability

Turns the platform from request-driven into continuously observing, and adds
the machinery an agency needs to trust what it reports: measured provider
health, operator-defined alerting, real ATSPM performance measures, an
auditable optimiser, an isolated scenario sandbox, a grounded Copilot, and a
tamper-evident ledger.

### Added — event-driven core

- **Typed event bus** (`app/events/`) with a closed topic vocabulary.
  Publishing an undeclared topic raises in development rather than producing an
  event nobody receives and no error anybody sees.
- **Per-subscriber bounded queues with visible backpressure.** A slow consumer
  has its *oldest* event dropped and the loss counted; the count is reported to
  that client as a `stream.status` frame and shown in the console's status
  strip. An unbounded queue would turn one stalled console into server memory
  growth; a silent drop would let an operator believe they had seen everything.
- **The WebSocket gateway is now authenticated** and supports per-client topic
  subscriptions (`signal.*`, `incident.*`, `*`). It previously accepted any
  unauthenticated client and broadcast everything to everyone.
- The gateway states on connect that **an open socket is not a claim that data
  is flowing**, and the console badge distinguishes `CONNECTED · QUIET` from
  live.

### Added — provider health & circuit breakers

- **Measured health per provider**: heartbeat, latency p50/p95, error rate,
  last success, last failure — with **hysteresis** so a flapping endpoint does
  not flood the notification centre. Degrade fast, recover slowly, by design.
- **`UNKNOWN` is a real state.** A provider nobody has probed has not been shown
  to work, and is never coloured green because nothing has failed yet.
- **Circuit breakers** on the weather and NTCIP adapters. A tripped breaker
  refuses the call with a stated reason rather than serving a cached value as
  current — so an open circuit shows as DISCONNECTED, which is the truth.
- `GET /api/v1/health/providers` and `/health/stream`, plus a console page.

### Added — alert & rules engine

- Operator-defined rules over real stored state: detector silent, sustained
  occupancy, controller state, provider degraded, safety-engine rejections.
- **A condition that cannot be evaluated is `INSUFFICIENT_DATA`, never false.**
  "The detector went silent" and "no detector has ever reported here" look
  identical to a naive timestamp test and mean completely different things;
  conflating them teaches operators to ignore the alarm that matters.
- Dedupe, cooldown, escalation, and delivery over UI, webhook and email.
  **A channel with no destination configured records `SKIPPED_NOT_CONFIGURED`,
  not `DELIVERED`** — a rule listing EMAIL with no SMTP host has not notified
  anybody.
- Every evaluation stores the values it saw, so a firing can be explained after
  the fact. Dry-run evaluation writes nothing.

### Added — observed signal state & real ATSPM analytics

- **`signal_state_logs`**: observed phase state, written on every readable
  controller poll. Arrival-on-green, split failures and progression cannot be
  computed from a current-state snapshot, and a gap in this table is an honest
  record of a period nobody observed.
- **NTCIP polling service** that records that state continuously, skips
  controllers whose circuit is open, and reports skips rather than hiding them.
- **Real performance measures**: throughput, occupancy, space-mean speed,
  control delay with HCM level of service, split failures and arrival-on-green.
- **`INSUFFICIENT_DATA` and `NOT_COMPUTABLE` are distinguished throughout**,
  because they have different remedies: wait/widen the window, versus connect
  something. Every measure reports its sample size, its minimum, its method and
  the inputs it used.
- Throughput refuses to convert counts into an hourly rate when the observation
  window was not recorded.
- Time-of-day profiles report hours with no samples as such, drawn as a hatched
  void rather than a zero bar that reads as "no traffic".

### Added — explainable optimiser & scenario sandbox

- **Webster's optimum cycle length**, split allocation bounded by each phase's
  configured green envelope, HCM v/c, and Webster uniform + random delay — with
  a **full calculation trace**: every intermediate value with its symbol,
  formula and source, so an engineer can check the arithmetic.
- **It refuses rather than guesses.** Demand at or above capacity returns
  `DEMAND_AT_OR_ABOVE_CAPACITY` with an explanation; thin measured data returns
  `INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST`. An over-saturated movement's delay
  is reported as unbounded, not as a large finite number.
- Recommendations are **validated by the Safety Engine** and cannot be applied
  if that verdict fails.
- **Scenario sandbox in its own table** (`scenario_runs`), not a flag on
  `traffic_metrics` — a flag is one forgotten `WHERE` clause away from a
  hypothetical appearing on the operations map as an observation. Output is
  stamped `SCENARIO / HYPOTHETICAL`, uses deliberately different field names,
  and is banded in the UI. A test asserts it writes to no observed-data table.
- A scenario compares against measured conditions only when enough real samples
  exist; otherwise the comparison is refused rather than computed against an
  assumed baseline.

### Added — grounded Copilot 2.0

- **Tool calling over real endpoints**: junction state, open incidents,
  performance measures, recent commands, provider health, open alerts,
  standards search.
- **Every claim carries a citation** to a record id and timestamp, or a
  standard and section. A tool that finds nothing returns `NO_DATA` with a
  reason, never an empty result a caller could read as zero.
- **Answers are assembled from tool results, not generated from them.** When
  tools return nothing, the answer says so and stops rather than reasoning
  about what the data would probably show.
- Per-operator session memory that holds the conversation, **not derived
  facts** — every answer re-queries, because "still 42 vehicles" is a claim
  about now.
- Works fully without an LLM key under a deterministic planner, and states
  which mode produced each answer.

### Added — incident lifecycle

- Triage → acknowledgement → assignment → resolution with **live SLA clocks**.
- **SLA targets are copied onto the incident at creation**, so tightening a
  policy next month does not retroactively turn last month's met targets into
  breaches.
- **Append-only timeline** with no update or delete path. A correction is a new
  entry referencing the one it corrects, so a review sees both what was
  believed at the time and what was later established.
- **Evidence must reference a record the platform stored** — a frame it
  ingested, an observation it recorded, a command it issued. There is no
  free-form upload path, and the referenced row is snapshotted so evidence
  survives retention pruning.
- Post-incident reports that **list their gaps** rather than leaving a reader
  to fill them.

### Added — governance

- **Tamper-evident hash-chained audit ledger.**
  `entry_hash = SHA256(sequence || previous_hash || canonical_json(entry))`.
  `/governance/audit/verify` recomputes every hash and reports the first break
  and its type (`ENTRY_MODIFIED`, `SEQUENCE_GAP`, `PREVIOUS_HASH_MISMATCH`).
  The UI states plainly that this makes tampering **detectable, not
  impossible**, and the export exists so an agency can anchor the chain outside
  its own database.
- **Fine-grained scopes** replacing coarse role checks. The whole access model
  is one readable table and is served as data. An AUDITOR reads everything and
  changes nothing, deliberately not a superset of OPERATOR.
- **Scoped API keys**, hashed at rest and shown exactly once. A key can never
  hold `signal:command`: issuing a signal change requires a named accountable
  operator, and a shared machine credential would record a meaningless actor in
  the ledger. A key cannot hold a scope its creator lacks.
- **Rate limiting** with a deliberately tight bucket for signal commands — far
  below any plausible human rate, because a cabinet being flooded with SNMP
  SETs is a safety concern even when the Safety Engine rejects every one.

### Added — import, reporting & observability

- **CSV / GeoJSON / GTFS import** with two-pass validation. `commit=false`
  returns the full report and writes nothing; every rejected row is listed with
  its row number and reason; physical bounds are enforced at the boundary so an
  impossible value never enters the database. Every imported record carries its
  source filename, content hash and import id.
- **GTFS static creates no transit events**: a schedule says a bus is due, not
  that one arrived.
- **Reports** (daily operations, signal performance, post-incident) in JSON,
  CSV and PDF. A measure that could not be computed appears with its reason and
  sample size rather than being omitted — an omitted section reads as "nothing
  happened", which is a different claim from "nothing was measured". PDF
  generation is dependency-free.
- **Structured JSON logging with request trace IDs**, returned in
  `X-Request-ID`, and a Prometheus `/metrics` endpoint.
- **No traffic measurement is exported to Prometheus.** A scrape strips source,
  timestamp and quality state, and a gauge reading `occupancy_pct 42` says
  nothing about whether that detector reported four seconds or forty minutes
  ago. A test enforces this.

### Fixed

- **The audit chain was never applied outside a running application.** The
  listener installed during app startup, so any audit row written by a script,
  a migration helper or a test was silently unchained — a gap in a ledger whose
  whole purpose is that gaps are not silent. Registration moved to model-import
  time.
- **The chain never verified.** Hashing ran in `before_flush`, before
  SQLAlchemy applied the `timestamp` column default, so the digest covered a
  null timestamp that the stored row later had. A second defect: the value
  written was timezone-aware while the naive column read it back without an
  offset. Both are now materialised and normalised before hashing.
- **The rules engine could not dispatch any condition.** Evaluators were stored
  in a dict at class-definition time, capturing `classmethod` objects whose
  `cls` argument then consumed `db`, shifting every parameter.
- **`find_intersection` could never resolve a junction from a question.** It
  tested whether the whole query was a substring of the junction name, so "what
  is the delay at Main St?" matched nothing. It now matches in both directions.
- Optional request fields defaulting to `None` defeated `.get(key, default)` in
  the optimiser and sandbox, crashing on saturation flow and demand source.

---

## [Unreleased] — Phase 1: Interactive Operations Console

Builds the operator-facing console on the Phase 0 foundations. The organising
idea: an operator should be able to see *where* a number came from, *how old*
it is, and *which rule* stopped a command — without leaving the screen they are
on.

### Added — provenance primitives

- **`MeasuredValue` is now the only sanctioned way to render telemetry.** It
  cannot be used without supplying provenance, so invariant 2 is enforced by
  the component API rather than by review. A missing value renders as its
  truthful absence ("NOT MEASURED"), never as zero.
- **Live-ticking data ages.** `useTickingAge` anchors to the observation's
  absolute timestamp rather than incrementing a counter, so a backgrounded tab
  catches up instead of under-reporting age. Quality state is recomputed from
  the ticking age: a reading that goes stale while a panel is open changes
  colour in place instead of claiming FRESH indefinitely.
- `ProvenanceChip`, `ProvenanceCard`, `QualityDot`, and a single
  `lib/quality.ts` vocabulary shared by every surface. Thresholds come from the
  backend, so the console and server can never disagree about what STALE means.

### Added — real-time

- **`useEventStream`**: one typed WebSocket client for the whole console, with
  topic subscriptions (`signal.*`, `incident.*`, `*`), exponential backoff with
  jitter, and keepalives. Pages subscribe instead of polling; the remaining
  poll is a 30s backstop for state that changed while the socket was down.
- **The connection badge distinguishes "connected" from "live".** An open
  socket is not evidence of flowing data, so the badge reports the socket state
  and the age of the last real event separately — `CONNECTED · QUIET` is a
  distinct, and honest, reading.
- **Notification centre and toasts**, driven exclusively by events the backend
  emitted. Nothing fires on a timer; a quiet control room produces an empty
  centre.

### Added — layered GIS map

- **Markers are coloured by data quality, not by a status word.** A junction
  reporting HEALTHY from telemetry that stopped four minutes ago is drawn as
  unmonitored.
- **Clusters inherit the worst quality of their members**, never an average, so
  one degraded junction stays visible at city zoom. Clustering is implemented
  in-repo (no `leaflet.markercluster` dependency) specifically to get that rule.
- Toggleable layers (junctions, incidents, cameras, sensors, weather, transit)
  with per-layer counts and a stated reason for every empty layer.
- Hover provenance card on every marker: source, absolute timestamp, live age
  and quality state.
- Draw-to-select an area for a bulk report, implemented with Leaflet primitives
  rather than `leaflet-draw`.
- Devices declare `position_source`: cameras and sensors have no coordinates of
  their own and inherit the junction's, which the map states rather than
  scattering markers to look convincing.

### Added — guided signal command workflow

- Four steps: **propose → validate → confirm → result**, with
  `POST /api/v1/signals/commands/validate` as a true dry run of the real path.
- **The Safety Engine now returns a per-rule verdict** (`SafetyCheck`: code,
  label, pass/fail, plain-language detail, source standard). The preview renders
  one row per rule, so an operator reads "phase 4 conflicts with the phase
  showing green" instead of a rejection code.
- The preview optionally re-reads the controller first, so the verdict is
  computed against the phase the hardware is displaying now.
- **The result reports what the controller did**, which is a different claim
  from what was requested: a hold accepted for a phase that is not currently
  green reads `ACCEPTED_BY_CONTROLLER_NOT_YET_DISPLAYING`.
- The Signals page no longer issues commands directly; the guided flow is the
  only path in the UI.

### Added — junction drawer, replay, explainability, onboarding

- **Junction drawer**: live phase state, detectors and cameras with per-device
  provenance, and a merged events timeline (incidents, commands, preemptions,
  audit entries). When controller state is unreadable it shows
  `SIGNAL STATE: UNAVAILABLE` rather than freezing on the last phase it saw.
- **Time scrubber** replaying real stored telemetry. Playback steps
  sample-to-sample rather than on a wall clock, gaps are detected and labelled
  rather than glided across, and a window with fewer than 3 samples refuses to
  draw a trend.
- **Explainable AI panel** with "Why this recommendation?" and "What data is
  missing?", every input carrying its own quality, and the Safety Engine's
  verdict. A proposal that fails safety cannot be applied, and applying one
  opens the same guided workflow an operator uses.
- **Onboarding wizard** as the core empty-state experience: junction →
  controller → camera → detector → weather, each ending in a live connectivity
  test that reports the actual network error on failure.

### Added — endpoints

- `GET /api/v1/map` — layered features with per-feature provenance; junction
  quality rolls up **worst-source-wins** across controller and telemetry.
- `GET /api/v1/timeline/{id}` — merged junction event feed.
- `GET /api/v1/timeline/{id}/replay` — stored telemetry for the scrubber, with
  `interpolation: NONE_GAPS_ARE_PRESERVED`.
- `POST /api/v1/signals/commands/validate` — dry run; writes nothing and does
  not consume the idempotency key (both pinned by tests).

### Added — design polish

- **Dark theme** via token redefinition, defined twice (behind
  `prefers-color-scheme`, guarded so an explicit light choice wins, and for an
  explicit dark choice) so the toggle works in both directions.
- Density toggle, wallboard mode for control-room screens, `?` shortcut sheet
  (every listed key is actually bound), skeleton loaders that carry no digits,
  visible focus rings, `prefers-reduced-motion` support, and responsive
  breakpoints.
- Command palette v2: navigate, run actions, or ask the grounded Copilot.
  Signal changes from the palette open the guided workflow — a palette should
  not be a fast path to a phase change.

### Fixed

- **Junction map markers had no provenance to colour by** (caught by a Phase 1
  test): junction features carried nested controller and traffic quality but no
  top-level envelope, so every junction would have rendered UNKNOWN. Added the
  worst-source-wins roll-up plus `quality_basis` naming its sources.
- Dashboard inspector defaulted unknown geometry to "4 LEG JUNCTION" and
  unknown control type to "NEMA TS2". Both now report that the geometry is not
  configured.
- `Math.random()` was briefly used for client list keys and reconnect jitter;
  both moved into `lib/entropy.ts` behind `crypto.getRandomValues`, isolated and
  documented, so a repository-wide search for fabricated data finds one file
  with an explicit justification.

### Removed

- `GisMap.tsx` and `AlertDrawer.tsx`, superseded by `OperationsMap` and the
  notification centre.

---

## [Unreleased] — Phase 0: Truthfulness Remediation & Foundations

Phase 0 repairs places where the platform displayed values it had not measured,
and puts the schema, the test suite and the controller integration on a footing
the later phases can build on.

### Fixed — values the console asserted but never measured

- **Signal controller state.** The generic controller adapter returned a
  hardcoded phase 2, a fabricated `active_plan: 1`, and a cycle position
  computed as `int(time.time()) % 90`. `send_command` wrote to no socket and
  returned success, and the API then recorded that unverified phase on the
  controller row — so the console drew a phase the hardware had never entered,
  and the safety engine's minimum-green check was validated against it.
  Adapters now read real state or report `None` with a reason.
- **Emergency preemption bypassed the safety engine.** `POST /api/v1/emergency`
  set `safety_clearance_passed = True` unconditionally. Every preemption call is
  now validated by `DeterministicSafetyEngine` and records the full verdict.
  (The endpoint also expected query parameters while the console posted a JSON
  body, so it had never succeeded; it now takes a typed request body.)
- **Camera stream properties.** A bare TCP handshake yielded `fps: 25.0` and
  `resolution: "1920x1080"`. Both are now `null` with an explicit
  `measurement_status`, and a reachable camera is `REACHABLE`, not `CONNECTED`
  — the latter is reserved for one that has actually delivered frames.
- **Forecast model metrics.** The forecast endpoint returned
  `{"mae": 3.4, "rmse": 4.8}` for a model that does not exist. It now reports
  `NO_FORECAST_MODEL_REGISTERED` with null metrics.
- **Dashboard grid health and latency.** Network health was floored at 75 %
  (`Math.max(75, …)`) regardless of real state, and API latency was seeded at
  `12` ms and clamped to 8–85 ms. Both now report measured values, or
  "NOT MEASURED" / "NONE CONFIGURED" when there is nothing to measure.
- **Corridor coordination values.** Per-junction offsets were rendered from
  list position (`idx * 12` seconds) and every link showed "BANDWIDTH: 45 %".
  Both now read "NOT CONFIGURED" / "NO DATA".
- **Analytics panel.** "MMU: 0 Faults / Nominal" and "Database State:
  SYNCHRONIZED" were hardcoded. MMU fault logs are not polled by any adapter,
  so they read "NOT POLLED"; database state comes from a live probe.
- **Status strip.** Four indicators were pinned to green ("REST API ONLINE",
  "POSTGRES / SQLITE READY", "NEMA TS2 ENGINE: RIGID") alongside a
  "SAFETY INTERLOCK: ACTIVE" badge, none of them measured. They now reflect
  real probes, and the safety-engine badge states the routing fact
  ("COMMANDS ROUTED VIA SAFETY ENGINE") rather than posing as a liveness light.
- **Map markers.** Unknown status rendered as a green marker reading "HEALTHY"
  and "CONNECTED" via `||` defaults. Unknown is now slate-grey, "UNKNOWN" and
  "NOT REPORTED".
- **Traffic metric derivations.** `flow_rate_vph` silently assumed a one-minute
  sample window; queue spacing (6 m/veh) and discharge rate (1.5 veh/s) were
  undeclared constants; a missing occupancy defaulted to `0.5` so that traffic
  pressure stayed printable; and every aggregate was stamped `FRESH` regardless
  of how old its inputs were. Flow rate now requires a declared
  `sample_window_sec`, the constants travel in `provenance.assumptions`,
  pressure is null without observed occupancy, and freshness is derived from
  the newest contributing observation.

### Fixed — correctness

- **No WebSocket message had ever reached the UI.** The client tested
  `payload.type` while the server sends `{event, timestamp, payload}`, so every
  live event was silently discarded and the console ran entirely on a
  15-second poll.
- **Conflicting movements could be approved during a clearance interval.**
  No phase displays green during yellow change or all-red, so `active_phase`
  reads null and the conflict matrix — which only consulted `active_phase` —
  approved a conflicting movement while the opposing approach was still
  clearing the intersection. Controllers now record the phases observed in
  clearance (`signal_controllers.clearing_phases`, migration `0003_clearance`)
  and the engine runs a `CLEARANCE_INTERVAL_CONFLICT_CHECK` against them.
  Found by an end-to-end run against the emulator, where a preemption to a
  conflicting phase was granted mid-yellow.
- **Naive/aware datetime crash in the safety engine.** SQLite returns naive
  datetimes, so the minimum-green check raised `TypeError` for any controller
  loaded from the database — a 500 on every command against a persisted
  controller with a phase start. Timestamps are normalised to UTC.

### Added

- **Real NTCIP 1202 integration.** `Ntcip1202Adapter` speaks SNMPv1 over UDP,
  reading `phaseStatusGroup` bitmaps and issuing holds through
  `phaseControlGroupHold`, with a post-command read-back as evidence.
  Supported by a dependency-free SNMPv1/BER codec (`app/providers/snmp_codec.py`)
  and a documented OID map (`app/providers/ntcip_objects.py`).
- **NTCIP 1202 controller emulator** (`backend/tools/ntcip_emulator.py`): a UDP
  SNMP agent backed by a real dual-ring barrier sequencer. It emulates
  controller behaviour and reports **no** vehicle counts, occupancies or
  detector calls. See "How to demo this truthfully" in the README.
- **Alembic migrations.** `0001_baseline` captures the pre-Phase-0 schema and
  `0002_phase0` adds `traffic_metrics.sample_window_sec` and
  `emergency_events.safety_report`; `0003_clearance` adds
  `signal_controllers.clearing_phases`. The API verifies the schema at startup and
  refuses to boot on drift in production.
- **Isolated test database.** `tests/conftest.py` redirects `DATABASE_URL` to a
  throwaway file before any application import; the suite previously read and
  wrote the operator's real `trafficintel.db`. The test schema is built through
  the migrations, so every run exercises the upgrade path.
- **28 new tests** covering adapter honesty, clearance-interval conflicts, the NTCIP wire protocol against
  the emulator, controller state synchronisation, preemption through the safety
  engine, the traffic-metric assumptions and quality derivation, and schema
  currency.

### Security

- CORS no longer sends `allow_origins=["*"]` with `allow_credentials=True` (a
  combination browsers reject); it uses the configured origin allow-list.
- The application refuses to start in `ENVIRONMENT=production` while
  `SECRET_KEY` is the placeholder published in this repository, and logs a
  warning in development.
- `POST /api/v1/sensors/{id}/telemetry` now requires authentication. It was
  open, so anyone on the network could write observations the console then
  presented as measured roadway data.
- `/health` and `/api/v1/settings/status` distinguish **measured** subsystems
  from merely **configured** ones, and no longer claim a PyTorch inference
  engine that is not installed.

### Known gaps carried into Phase 1/2

- MMU/CMU fault log polling is not implemented for any adapter.
- `operational_mode`, `active_plan` and `cycle_second` are not yet polled from
  NTCIP controllers and are reported as unread.
- The RAG knowledge base indexes paraphrased summaries of MUTCD 4D / NEMA TS 2
  while citing them by section. Verbatim sourcing and citation accuracy are
  part of the Grounded Copilot 2.0 work in Phase 2.
