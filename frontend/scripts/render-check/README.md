# Phase 3 render check

Renders the Phase 3 components to HTML with `renderToString` and asserts that
the truthfulness invariants survive into the markup an operator would see.

```bash
npm run check:render
```

`tsc -b` and `vite build` do not prove any of this. A component can compile and
bundle cleanly and still throw on `undefined.map`, or — the failure that matters
for this platform — render a confident `0` where the API returned `null`.

64 assertions across the trust panel, stringline, verification panel, the
handover snapshot, and every declared empty state.

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
