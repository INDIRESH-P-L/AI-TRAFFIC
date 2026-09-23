import React, { useMemo, useState } from 'react';
import { Ruler } from 'lucide-react';

/**
 * TRAFFICINTEL AI - Corridor Time-Space Diagram (Stringline)
 *
 * The classic coordination diagram: distance up the y-axis, time across the
 * x-axis, one horizontal track per junction, green bands drawn where that
 * junction was OBSERVED displaying green.
 *
 * What makes this version truthful, and what the drawing has to preserve:
 *
 *   - Bands come from polled controller state, not from a timing plan. A
 *     timing plan says what the controller was told to do; this says what it
 *     was seen doing.
 *   - Periods with no observations are hatched, never drawn through. The
 *     tempting bug is to connect the last sample before a gap to the first
 *     one after it, which invents signal state for the dark period.
 *   - Band edges are uncertain by up to one poll interval. That uncertainty
 *     is drawn as a fade at each edge, so a band never claims a sharper
 *     transition than the sampling supports.
 *   - The progression line between junctions is drawn ONLY for segments the
 *     backend computed a speed for. Segments refused for being below
 *     measurement resolution are listed in words instead - drawing a line
 *     there would render an artefact of division as a green wave.
 */

interface Band {
  phase: number;
  start: string;
  end: string;
  duration_sec: number;
  closed: boolean;
}

interface Gap {
  start: string;
  end: string;
  duration_sec: number;
  reason: string;
}

interface StringlineJunction {
  intersection_id: string;
  name: string;
  code: string | null;
  position_m: number;
  bands: Band[];
  gaps: Gap[];
  observation_count: number;
  poll_interval_sec: number | null;
  edge_uncertainty_sec: number | null;
  empty_reason: string | null;
}

export interface StringlineResult {
  status: string;
  corridor_name?: string;
  coordination_mode?: string | null;
  configured_cycle_length_sec?: number | null;
  window_start?: string;
  window_end?: string;
  window_minutes?: number;
  corridor_length_m?: number;
  junction_count?: number;
  junctions_with_observations?: number;
  junctions?: StringlineJunction[];
  progression?: {
    segments: any[];
    segments_computed: number;
    segments_total: number;
    segments_below_resolution?: number;
    empty_reason: string | null;
    resolution_note?: string;
  };
  empty_reason?: string | null;
  data_basis?: string;
  distance_basis?: string;
  detail?: string;
}

const PHASE_COLORS: Record<number, string> = {
  2: '#22c55e',
  4: '#38bdf8',
  6: '#16a34a',
  8: '#0ea5e9',
};

const phaseColor = (phase: number): string =>
  PHASE_COLORS[phase] || 'var(--its-text-accent)';

const PAD = { top: 26, right: 18, bottom: 40, left: 132 };
const TRACK_HEIGHT = 26;
const TRACK_GAP = 22;

export const StringlineDiagram: React.FC<{ result: StringlineResult }> = ({ result }) => {
  const [hover, setHover] = useState<string | null>(null);

  // Memoised against the response field rather than a fresh `|| []`, which
  // would be a new array identity on every render and defeat the geometry
  // memo below entirely.
  const junctions = useMemo(() => result.junctions ?? [], [result.junctions]);

  const geometry = useMemo(() => {
    const startMs = result.window_start ? Date.parse(result.window_start) : 0;
    const endMs = result.window_end ? Date.parse(result.window_end) : startMs + 1;
    const spanMs = Math.max(endMs - startMs, 1);

    // Junctions are laid out by their real position along the corridor, so the
    // slope of a progression line means something. Tracks are ordered upstream
    // to downstream with the furthest junction at the top, matching the
    // convention operators read on paper diagrams.
    const ordered = [...junctions].sort((a, b) => b.position_m - a.position_m);

    const height = PAD.top + PAD.bottom + ordered.length * (TRACK_HEIGHT + TRACK_GAP);
    const width = 980;
    const plotWidth = width - PAD.left - PAD.right;

    const xFor = (iso: string) =>
      PAD.left + ((Date.parse(iso) - startMs) / spanMs) * plotWidth;

    const yFor = (index: number) => PAD.top + index * (TRACK_HEIGHT + TRACK_GAP);

    return { startMs, endMs, spanMs, ordered, height, width, plotWidth, xFor, yFor };
  }, [junctions, result.window_start, result.window_end]);

  // Time gridlines at a readable interval for the window length.
  const ticks = useMemo(() => {
    const minutes = result.window_minutes || 15;
    const stepSec = minutes <= 5 ? 30 : minutes <= 20 ? 120 : minutes <= 60 ? 300 : 900;
    const out: { x: number; label: string }[] = [];
    for (let t = geometry.startMs; t <= geometry.endMs; t += stepSec * 1000) {
      out.push({
        x: PAD.left + ((t - geometry.startMs) / geometry.spanMs) * geometry.plotWidth,
        label: new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      });
    }
    return out;
  }, [geometry, result.window_minutes]);

  if (!junctions.length) return null;

  const computedSegments = (result.progression?.segments || []).filter(
    (s: any) => s.status === 'COMPUTED',
  );

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg
        width={geometry.width}
        height={geometry.height}
        role="img"
        aria-label={`Time-space diagram for ${result.corridor_name || 'corridor'}`}
        style={{ display: 'block', minWidth: `${geometry.width}px` }}
      >
        <defs>
          {/* Hatching marks periods with no observations. Deliberately drawn
              as a texture rather than a colour, so it reads as "absent" and
              can never be mistaken for a state. */}
          <pattern id="sl-gap" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="var(--its-bg-base)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--its-border-strong, #555)" strokeWidth="2" />
          </pattern>

          {/* Edge fade: a band's true start/end is only known to within one
              poll interval, so the ends are soft. */}
          <linearGradient id="sl-edge-left" x1="0" x2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0.75" />
          </linearGradient>
          <linearGradient id="sl-edge-right" x1="0" x2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.75" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Time gridlines */}
        {ticks.map((tick, i) => (
          <g key={`tick-${i}`}>
            <line
              x1={tick.x}
              y1={PAD.top - 6}
              x2={tick.x}
              y2={geometry.height - PAD.bottom + 6}
              stroke="var(--its-border-subtle)"
              strokeDasharray="2 4"
            />
            <text
              x={tick.x}
              y={geometry.height - PAD.bottom + 20}
              textAnchor="middle"
              fontSize="9"
              fill="var(--its-text-muted)"
              className="mono"
            >
              {tick.label}
            </text>
          </g>
        ))}

        {/* Progression lines, drawn only where a speed was actually computed */}
        {computedSegments.map((segment: any, i: number) => {
          const fromIndex = geometry.ordered.findIndex((j) => j.name === segment.from);
          const toIndex = geometry.ordered.findIndex((j) => j.name === segment.to);
          if (fromIndex < 0 || toIndex < 0) return null;

          const fromJunction = geometry.ordered[fromIndex];
          const firstBand = fromJunction.bands[0];
          if (!firstBand) return null;

          const x1 = geometry.xFor(firstBand.start);
          const x2 = x1 + (segment.median_offset_sec / (geometry.spanMs / 1000)) * geometry.plotWidth;

          return (
            <line
              key={`prog-${i}`}
              x1={x1}
              y1={geometry.yFor(fromIndex) + TRACK_HEIGHT / 2}
              x2={x2}
              y2={geometry.yFor(toIndex) + TRACK_HEIGHT / 2}
              stroke="var(--its-text-accent)"
              strokeWidth="1.5"
              strokeDasharray="5 3"
              opacity="0.65"
            >
              <title>
                {`${segment.from} to ${segment.to}: median observed offset ` +
                  `${segment.median_offset_sec}s over ${segment.distance_m}m, implying ` +
                  `${segment.implied_progression_speed_kph} km/h. ${segment.caveat || ''}`}
              </title>
            </line>
          );
        })}

        {/* One track per junction */}
        {geometry.ordered.map((junction, index) => {
          const y = geometry.yFor(index);
          const uncertainty = junction.edge_uncertainty_sec || 0;
          const edgePx =
            uncertainty > 0
              ? Math.min((uncertainty / (geometry.spanMs / 1000)) * geometry.plotWidth, 14)
              : 0;

          return (
            <g key={junction.intersection_id}>
              {/* Track label */}
              <text x={PAD.left - 10} y={y + 11} textAnchor="end" fontSize="10" fontWeight="600" fill="var(--its-text-primary)">
                {junction.name.length > 20 ? `${junction.name.slice(0, 19)}...` : junction.name}
              </text>
              <text x={PAD.left - 10} y={y + 23} textAnchor="end" fontSize="9" fill="var(--its-text-muted)" className="mono">
                {junction.position_m.toFixed(0)} m
              </text>

              {/* Baseline track - the "no green observed" ground */}
              <rect
                x={PAD.left}
                y={y}
                width={geometry.plotWidth}
                height={TRACK_HEIGHT}
                fill="var(--its-bg-base)"
                stroke="var(--its-border-subtle)"
              />

              {/* Observation gaps, hatched over the whole track height */}
              {junction.gaps.map((gap, gi) => {
                const x = geometry.xFor(gap.start);
                const w = Math.max(geometry.xFor(gap.end) - x, 1.5);
                return (
                  <rect
                    key={`gap-${gi}`}
                    x={x}
                    y={y}
                    width={w}
                    height={TRACK_HEIGHT}
                    fill="url(#sl-gap)"
                    onMouseEnter={() =>
                      setHover(
                        `${junction.name}: no observations for ${gap.duration_sec}s. ` +
                          'Signal state during this period is unknown and is not drawn.',
                      )
                    }
                    onMouseLeave={() => setHover(null)}
                  >
                    <title>
                      {`NO OBSERVATIONS - ${gap.duration_sec}s. State during this period is ` +
                        'unknown; the diagram does not interpolate across it.'}
                    </title>
                  </rect>
                );
              })}

              {/* Observed green bands */}
              {junction.bands.map((band, bi) => {
                const x = geometry.xFor(band.start);
                const w = Math.max(geometry.xFor(band.end) - x, 2);
                const color = phaseColor(band.phase);

                return (
                  <g
                    key={`band-${bi}`}
                    onMouseEnter={() =>
                      setHover(
                        `${junction.name} phase ${band.phase}: green for ${band.duration_sec}s` +
                          (band.closed ? '' : ' (still green at the edge of the window)') +
                          (uncertainty ? `. Edges uncertain by up to ${uncertainty}s.` : ''),
                      )
                    }
                    onMouseLeave={() => setHover(null)}
                    style={{ color }}
                  >
                    <rect x={x} y={y + 3} width={w} height={TRACK_HEIGHT - 6} fill={color} opacity="0.75" />

                    {/* Soft edges showing sampling uncertainty */}
                    {edgePx > 0 && (
                      <>
                        <rect x={x} y={y + 3} width={Math.min(edgePx, w / 2)} height={TRACK_HEIGHT - 6} fill="url(#sl-edge-left)" />
                        <rect
                          x={x + w - Math.min(edgePx, w / 2)}
                          y={y + 3}
                          width={Math.min(edgePx, w / 2)}
                          height={TRACK_HEIGHT - 6}
                          fill="url(#sl-edge-right)"
                        />
                      </>
                    )}

                    {/* An interval still green at the window edge gets a dashed
                        terminator: we never observed it end. */}
                    {!band.closed && (
                      <line
                        x1={x + w}
                        y1={y + 2}
                        x2={x + w}
                        y2={y + TRACK_HEIGHT - 2}
                        stroke={color}
                        strokeWidth="2"
                        strokeDasharray="2 2"
                      />
                    )}

                    <title>
                      {`Phase ${band.phase} observed green for ${band.duration_sec}s` +
                        (band.closed ? '.' : ' - still green at the end of the window.')}
                    </title>
                  </g>
                );
              })}

              {junction.empty_reason && (
                <text x={PAD.left + 10} y={y + 17} fontSize="10" fill="var(--its-text-muted)">
                  NO SIGNAL STATE OBSERVED IN THIS WINDOW
                </text>
              )}
            </g>
          );
        })}

        <text x={PAD.left} y={14} fontSize="9" fill="var(--its-text-muted)" letterSpacing="0.06em">
          OBSERVED GREEN INTERVALS - DISTANCE (VERTICAL) AGAINST TIME (HORIZONTAL)
        </text>
      </svg>

      {/* Legend and hover readout */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: '14px',
          padding: '9px 12px',
          borderTop: '1px solid var(--its-border-subtle)',
          fontSize: '10px',
          color: 'var(--its-text-muted)',
        }}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ width: '16px', height: '9px', background: '#22c55e', opacity: 0.75 }} />
          Observed green
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
          <span
            style={{
              width: '16px',
              height: '9px',
              backgroundImage:
                'repeating-linear-gradient(45deg, var(--its-border-strong, #555) 0 2px, var(--its-bg-base) 2px 4px)',
            }}
          />
          No observations (state unknown)
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
          <span
            style={{
              width: '16px',
              borderTop: '1.5px dashed var(--its-text-accent)',
              display: 'inline-block',
            }}
          />
          Measured progression offset
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
          <Ruler size={11} /> Soft band edges = sampling uncertainty
        </span>
        {hover && (
          <span style={{ flexBasis: '100%', color: 'var(--its-text-secondary)', paddingTop: '4px' }}>
            {hover}
          </span>
        )}
      </div>
    </div>
  );
};
