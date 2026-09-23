import type { QualityState } from '../../lib/quality';

/**
 * Grid clustering for the operations map.
 *
 * Implemented here rather than pulled from leaflet.markercluster for one
 * reason that matters to this platform: a cluster bubble has to inherit the
 * WORST data-quality state of its members, not an average or the first one
 * found. If a cluster of twelve junctions contains one whose telemetry has
 * gone stale, the operator must see that from the zoomed-out view. Averaging
 * would hide exactly the junction they need to look at.
 *
 * Grid size is in screen pixels, so clusters stay visually separated at every
 * zoom level without re-tuning a distance in metres.
 */

export interface ClusterableFeature {
  id: string;
  latitude: number;
  longitude: number;
  qualityState: QualityState;
  [key: string]: any;
}

export interface Cluster<T extends ClusterableFeature> {
  id: string;
  latitude: number;
  longitude: number;
  members: T[];
  /** Worst quality state among members — never an average. */
  worstQuality: QualityState;
}

/** Severity order: later entries dominate when merging a cluster. */
const SEVERITY: QualityState[] = [
  'FRESH',
  'UNKNOWN',
  'NO_DATA',
  'AGING',
  'STALE',
  'INVALID',
  'DISCONNECTED',
];

export function worstQuality(states: QualityState[]): QualityState {
  let worst: QualityState = 'FRESH';
  let worstRank = -1;
  for (const state of states) {
    const rank = SEVERITY.indexOf(state);
    if (rank > worstRank) {
      worstRank = rank;
      worst = state;
    }
  }
  return worstRank === -1 ? 'UNKNOWN' : worst;
}

export interface Projector {
  /** Project lat/lng to container pixel space at the current zoom. */
  project: (lat: number, lng: number) => { x: number; y: number };
}

export function clusterFeatures<T extends ClusterableFeature>(
  features: T[],
  projector: Projector,
  gridPx = 64,
): Array<Cluster<T>> {
  const cells = new Map<string, T[]>();

  for (const feature of features) {
    if (
      typeof feature.latitude !== 'number' ||
      typeof feature.longitude !== 'number' ||
      Number.isNaN(feature.latitude) ||
      Number.isNaN(feature.longitude)
    ) {
      continue; // A feature without coordinates is not placed at 0,0.
    }

    const point = projector.project(feature.latitude, feature.longitude);
    const key = `${Math.floor(point.x / gridPx)}:${Math.floor(point.y / gridPx)}`;
    const bucket = cells.get(key);
    if (bucket) bucket.push(feature);
    else cells.set(key, [feature]);
  }

  const clusters: Array<Cluster<T>> = [];
  cells.forEach((members, key) => {
    // Cluster anchor is the centroid of its members, so the bubble sits where
    // the junctions actually are rather than on an arbitrary grid corner.
    const latitude = members.reduce((sum, m) => sum + m.latitude, 0) / members.length;
    const longitude = members.reduce((sum, m) => sum + m.longitude, 0) / members.length;

    clusters.push({
      id: `cluster-${key}`,
      latitude,
      longitude,
      members,
      worstQuality: worstQuality(members.map(m => m.qualityState)),
    });
  });

  return clusters;
}
