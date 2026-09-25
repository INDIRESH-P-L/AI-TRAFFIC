# Phase 3 render check

Renders the Phase 3 components to HTML with `renderToString` and asserts that
the truthfulness invariants survive into the markup an operator would see.

```bash
npm run check:render
```

`tsc -b` and `vite build` do not prove any of this. A component can compile and
bundle cleanly and still throw on `undefined.map`, or — the failure that matters
for this platform — render a confident `0` where the API returned `null`.

134 assertions across the trust panel, stringline, verification panel, the
handover snapshot, the grounded-intelligence panels (anomaly, forecast,
fusion), and every declared empty state.

## What it asserts

- An `UNRATED` junction renders a dash, never a zero, and says on screen why a
  dash is not a zero.
- Every trust component and its weight reaches the markup; the limiting factor
  is named.
- Observation gaps in the stringline are painted with the hatch pattern, never
  a colour, and a progression line is drawn only for segments the backend
  actually computed a speed for.
- A confidence interval containing zero renders as `NO MEASURABLE CHANGE` with
  "interval contains 0" visible, and the method caveats are on screen rather
  than in a help page.
- `INSUFFICIENT_DATA` offers no verdict and states that absence of measurement
  is not evidence of absence of effect.
- The handover snapshot separates junctions that went unseen from those covered
  on some channels but not others, and names which channels did report.
- A null coverage mean renders as a dash, never `0.0`; an absent snapshot says
  `NO SNAPSHOT RECORDED`; a stringline with no junctions draws no axes at all,
  because empty axes read as "no green was displayed".

## Fixture provenance

These are **recorded API responses**, not invented data, and they exist only in
this test — nothing here is ever served to the console.

- `trust_*.json`, `stringline.json` — captured verbatim from a running backend
  polling three `tools/ntcip_emulator` controllers over real NTCIP 1202/SNMP.
  The stringline's observation gaps are genuine: they are a backend restart.
- `verify_*.json` — produced by calling the real `welch_compare()` serializer
  with sample arrays chosen to land on each verdict. The envelope is the
  genuine one; only the sample values are supplied by the generator.

To re-capture after an API change, see `backend/tools/` and the capture snippet
in the project CHANGELOG entry for Phase 3.

- `anomaly_*.json`, `forecast_*.json`, `fusion_*.json` — produced by
  `backend/tools/generate_intelligence_render_fixtures.py`, which runs the
  **real** anomaly detector, forecaster and fusion detector over **test
  telemetry** written to a throwaway SQLite database (deleted afterwards). The
  telemetry is deterministic (SHA-256-derived variation, as in the pytest
  suite), so the fixtures are reproducible. These are not field recordings;
  they are the genuine response shapes for each state the panels must handle.
  Regenerate after an API change with `python -m tools.generate_intelligence_render_fixtures`
  from `backend/`.

- `coordination_applied_live.json`, `coordination_verify_live.json` —
  **recorded from a live run**, not generated. A green-wave plan was proposed
  and applied through the real API to three `tools/ntcip_emulator` controllers
  on the Avinashi Road demo corridor. After several cycles, `verify` compared
  the plan with the offsets the platform's stringline observed (31.7 s and
  32.6 s against a planned 32 s).
- `coordination_not_computable.json`, `coordination_rejected_by_safety.json`,
  `tsp_dry_run.json`, `preemption_*.json` — produced by the same generator,
  running the real planner, TSP evaluator and preemption service. The
  preemption verdicts are real dispatches against an in-process NTCIP emulator
  (`ACTIVE`), a conflicting phase (`REJECTED`), and a stopped emulator
  (`FAILED`). The TSP buses are test feed entities, encoded as genuine
  GTFS-Realtime protobuf.
