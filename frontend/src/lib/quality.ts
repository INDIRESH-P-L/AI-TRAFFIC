/**
 * TRAFFICINTEL AI - Data Quality Vocabulary
 *
 * One definition of what a quality state means, what colour it takes, and how
 * an age reads in words. Every number the console shows is rendered through
 * these helpers, so a value can never appear without the operator being able
 * to see how old it is and where it came from.
 *
 * The thresholds come from the backend (`quality_thresholds_sec`), not from
 * constants duplicated here — a console that disagreed with the server about
 * what "STALE" means would be worse than one that did not label staleness at
 * all.
 */

export type QualityState =
  | 'FRESH'
  | 'AGING'
  | 'STALE'
  | 'DISCONNECTED'
  | 'INVALID'
  | 'NO_DATA'
  | 'UNKNOWN';

export interface QualityThresholds {
  fresh: number;
  aging: number;
  stale: number;
}

/** Provenance envelope the API attaches to every measured value. */
export interface Provenance {
  state: QualityState;
  age_sec: number | null;
  observed_at: string | null;
  source: string | string[] | null;
}

export const DEFAULT_THRESHOLDS: QualityThresholds = { fresh: 15, aging: 60, stale: 180 };

export function normalizeQuality(state: string | null | undefined): QualityState {
  const value = (state || 'UNKNOWN').toUpperCase();
  const known: QualityState[] = [
    'FRESH', 'AGING', 'STALE', 'DISCONNECTED', 'INVALID', 'NO_DATA', 'UNKNOWN',
  ];
  return (known as string[]).includes(value) ? (value as QualityState) : 'UNKNOWN';
}

/**
 * Recompute the state from an age the browser measured.
 *
 * The server's state was true when it serialised the response. A panel left
 * open drifts, so the age counter ticks locally and the state ticks with it —
 * otherwise a reading would keep claiming FRESH minutes after it went stale.
 */
export function qualityForAge(
  ageSec: number | null,
  thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
): QualityState {
  if (ageSec === null || Number.isNaN(ageSec)) return 'UNKNOWN';
  if (ageSec < 0) return 'INVALID';
  if (ageSec <= thresholds.fresh) return 'FRESH';
  if (ageSec <= thresholds.aging) return 'AGING';
  if (ageSec <= thresholds.stale) return 'STALE';
  return 'DISCONNECTED';
}

export interface QualityAppearance {
  color: string;
  background: string;
  border: string;
  label: string;
  /** What the state means, in words an operator can act on. */
  meaning: string;
}

export function qualityAppearance(state: QualityState): QualityAppearance {
  switch (state) {
    case 'FRESH':
      return {
        color: 'var(--its-signal-green)',
        background: 'var(--its-signal-green-bg)',
        border: 'var(--its-signal-green-border)',
        label: 'FRESH',
        meaning: 'Reported within the freshness window. Safe to act on.',
      };
    case 'AGING':
      return {
        color: 'var(--its-signal-yellow)',
        background: 'var(--its-signal-yellow-bg)',
        border: 'var(--its-signal-yellow-border)',
        label: 'AGING',
        meaning: 'Older than the freshness window but still recent. Verify before acting.',
      };
    case 'STALE':
      return {
        color: 'var(--its-signal-red)',
        background: 'var(--its-signal-red-bg)',
        border: 'var(--its-signal-red-border)',
        label: 'STALE',
        meaning: 'Too old to describe current conditions. Do not act on this value.',
      };
    case 'DISCONNECTED':
      return {
        color: 'var(--its-text-muted)',
        background: 'var(--its-stale-bg)',
        border: 'var(--its-border-default)',
        label: 'DISCONNECTED',
        meaning: 'The source has stopped reporting. This is the last value it sent, not a current one.',
      };
    case 'INVALID':
      return {
        color: 'var(--its-signal-red)',
        background: 'var(--its-signal-red-bg)',
        border: 'var(--its-signal-red-border)',
        label: 'INVALID',
        meaning: 'The reading failed physical bounds checks and was rejected.',
      };
    case 'NO_DATA':
      return {
        color: 'var(--its-text-muted)',
        background: 'var(--its-stale-bg)',
        border: 'var(--its-border-subtle)',
        label: 'NO DATA',
        meaning: 'No source has ever reported this value.',
      };
    default:
      return {
        color: 'var(--its-text-muted)',
        background: 'var(--its-stale-bg)',
        border: 'var(--its-border-subtle)',
        label: 'UNKNOWN',
        meaning: 'The platform has not established a state for this value.',
      };
  }
}

/** Compact age, e.g. "4s", "2m 10s", "3h 06m". Null renders as a dash, never 0. */
export function formatAge(ageSec: number | null): string {
  if (ageSec === null || Number.isNaN(ageSec)) return '—';
  if (ageSec < 0) return 'FUTURE';
  const s = Math.floor(ageSec);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${String(m % 60).padStart(2, '0')}m`;
  return `${Math.floor(h / 24)}d ${String(h % 24).padStart(2, '0')}h`;
}

/** Source list rendered for display. Arrays are joined; null is explicit. */
export function formatSource(source: string | string[] | null | undefined): string {
  if (!source) return 'NO SOURCE RECORDED';
  return Array.isArray(source) ? (source.join(', ') || 'NO SOURCE RECORDED') : source;
}

/** Absolute timestamp for the hover card, so the age counter is checkable. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return 'NEVER';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'UNPARSEABLE';
  return d.toISOString().replace('T', ' ').slice(0, 19) + 'Z';
}
