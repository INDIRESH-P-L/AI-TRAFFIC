/**
 * TRAFFICINTEL AI - Non-data randomness
 *
 * This platform forbids random numbers in anything an operator reads as data.
 * Two mechanisms still legitimately need entropy, and neither produces a value
 * that reaches the screen as a measurement:
 *
 *   - unique keys for client-side list items
 *   - jitter on reconnect backoff, so every open console does not retry a
 *     restarted backend on the same millisecond
 *
 * They live here, isolated and named for what they are, so a repository-wide
 * search for fabricated data finds one file with an explicit justification
 * rather than bare `Math.random()` calls scattered through the UI. Nothing in
 * this module may be used to produce a displayed value.
 */

function cryptoBytes(count: number): Uint8Array {
  const buffer = new Uint8Array(count);
  globalThis.crypto.getRandomValues(buffer);
  return buffer;
}

/** Opaque client-side identifier. Never an entity id, never displayed as data. */
export function clientId(prefix = 'c'): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return `${prefix}-${globalThis.crypto.randomUUID()}`;
  }
  const bytes = cryptoBytes(8);
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${prefix}-${Date.now().toString(36)}-${hex}`;
}

/**
 * Fraction in [0, 1) for retry jitter only.
 *
 * Not a measurement, not a sample, not a simulated value.
 */
export function jitterFraction(): number {
  const [a, b] = cryptoBytes(2);
  return ((a << 8) | b) / 65536;
}
