import { useEffect, useState } from 'react';

/**
 * Live-ticking age of an observation, in seconds.
 *
 * The API reports an age that was true when the response was serialised. An
 * operator staring at a wallboard needs that number to keep moving: a reading
 * frozen at "3s" for ten minutes is a lie the UI tells by omission.
 *
 * Anchored to the observation's absolute timestamp rather than incrementing a
 * counter, so a backgrounded tab (where timers are throttled) catches up
 * correctly instead of under-reporting the age.
 */
export function useTickingAge(
  observedAt: string | null | undefined,
  fallbackAgeSec: number | null = null,
  intervalMs = 1000,
): number | null {
  const anchorMs = observedAt ? new Date(observedAt).getTime() : NaN;
  const hasAnchor = !Number.isNaN(anchorMs);

  const compute = (): number | null => {
    if (hasAnchor) return (Date.now() - anchorMs) / 1000;
    return fallbackAgeSec;
  };

  const [age, setAge] = useState<number | null>(compute);

  useEffect(() => {
    setAge(compute());
    if (!hasAnchor) return;

    const timer = setInterval(() => setAge(compute()), intervalMs);

    // A throttled background tab leaves the age behind; recompute on return.
    const onVisibility = () => {
      if (document.visibilityState === 'visible') setAge(compute());
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [observedAt, fallbackAgeSec, intervalMs]);

  return age;
}
