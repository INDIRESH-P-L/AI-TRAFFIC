import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Camera as CameraIcon, Cloud, Crosshair, Layers, Maximize2, Bus,
  AlertTriangle, Radio, GitCommit, SquareDashedMousePointer,
} from 'lucide-react';
import {
  DEFAULT_THRESHOLDS, formatAge, formatSource, formatTimestamp,
  normalizeQuality, qualityAppearance, qualityForAge,
} from '../../lib/quality';
import type { Provenance, QualityState, QualityThresholds } from '../../lib/quality';
import { clusterFeatures, worstQuality } from './clustering';
import type { ClusterableFeature } from './clustering';

/**
 * TRAFFICINTEL AI - Layered GIS Operations Map
 *
 * Markers are coloured by DATA QUALITY, not by a status word. The distinction
 * is the whole point of the map: a junction reporting "HEALTHY" from telemetry
 * that stopped updating four minutes ago is not healthy, it is unmonitored,
 * and it is drawn as such. Clusters inherit the worst quality of their members
 * so a single degraded junction is still visible at city zoom.
 *
 * Every marker has a hover card showing source, timestamp and live-ticking age,
 * so provenance is one pointer movement away from any point on the map.
 */

export type LayerId = 'junctions' | 'cameras' | 'sensors' | 'incidents' | 'weather' | 'transit';

export interface MapLayerData {
  features: any[];
  empty_reason: string | null;
}

export interface MapData {
  generated_at: string;
  quality_thresholds_sec: QualityThresholds;
  layers: Partial<Record<LayerId, MapLayerData>>;
}

interface OperationsMapProps {
  data: MapData | null;
  loading?: boolean;
  error?: string | null;
  selectedId?: string | null;
  onSelectJunction?: (id: string) => void;
  onAreaSelect?: (junctionIds: string[]) => void;
  height?: string;
}

const LAYER_META: Record<LayerId, { label: string; icon: React.ReactNode; color: string }> = {
  junctions: { label: 'Junctions', icon: <GitCommit size={12} />, color: 'var(--its-text-accent)' },
  incidents: { label: 'Incidents', icon: <AlertTriangle size={12} />, color: 'var(--its-signal-red)' },
  cameras: { label: 'Cameras', icon: <CameraIcon size={12} />, color: 'var(--its-text-indigo)' },
  sensors: { label: 'Sensors', icon: <Radio size={12} />, color: 'var(--its-text-teal)' },
  weather: { label: 'Weather', icon: <Cloud size={12} />, color: 'var(--its-text-cyan)' },
  transit: { label: 'Transit', icon: <Bus size={12} />, color: 'var(--its-text-brand)' },
};

const LAYER_ORDER: LayerId[] = ['junctions', 'incidents', 'cameras', 'sensors', 'weather', 'transit'];

interface HoverTarget {
  x: number;
  y: number;
  title: string;
  subtitle: string;
  rows: Array<[string, string]>;
  provenance: Provenance | null;
  positionSource?: string;
}

/** Resolve a feature's current quality from its provenance envelope. */
function featureQuality(
  provenance: Provenance | null | undefined,
  thresholds: QualityThresholds,
  nowMs: number,
): QualityState {
  if (!provenance) return 'UNKNOWN';
  if (!provenance.observed_at) return normalizeQuality(provenance.state);
  const ageSec = (nowMs - new Date(provenance.observed_at).getTime()) / 1000;
  return qualityForAge(ageSec, thresholds);
}

export const OperationsMap: React.FC<OperationsMapProps> = ({
  data,
  loading = false,
  error = null,
  selectedId,
  onSelectJunction,
  onAreaSelect,
  height = '100%',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerLayerRef = useRef<L.LayerGroup | null>(null);
  const selectionRectRef = useRef<L.Rectangle | null>(null);

  const [activeLayers, setActiveLayers] = useState<Set<LayerId>>(
    () => new Set<LayerId>(['junctions', 'incidents']),
  );
  const [basemap, setBasemap] = useState<'esri' | 'osm'>('esri');
  const [zoom, setZoom] = useState(13);
  const [hover, setHover] = useState<HoverTarget | null>(null);
  const [areaMode, setAreaMode] = useState(false);
  const [renderTick, setRenderTick] = useState(0);

  const thresholds = data?.quality_thresholds_sec ?? DEFAULT_THRESHOLDS;

  // Sampled on the same tick that ages the markers, so render stays pure.
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  // Re-render markers periodically so quality colours age in place. Without
  // this, a junction that went stale while the operator watched would keep its
  // green marker until the next data refresh.
  useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
      setRenderTick(t => t + 1);
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  // --- Map initialisation ----------------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: [20, 0],
      zoom: 2,
      zoomControl: true,
      attributionControl: false,
    });

    L.control
      .attribution({ position: 'bottomright', prefix: 'TRAFFICINTEL GIS' })
      .addTo(map);

    map.on('zoomend', () => setZoom(map.getZoom()));
    map.on('move', () => setRenderTick(t => t + 1));

    markerLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;

    // Leaflet measures the container on creation; in a flex/grid shell that
    // size is often not final yet, which leaves grey tiles until a resize.
    const settle = setTimeout(() => map.invalidateSize(), 120);
    const onResize = () => map.invalidateSize();
    window.addEventListener('resize', onResize);

    return () => {
      clearTimeout(settle);
      window.removeEventListener('resize', onResize);
      map.remove();
      mapRef.current = null;
      markerLayerRef.current = null;
    };
  }, []);

  // --- Basemap ----------------------------------------------------------
  const tileLayerRef = useRef<L.TileLayer | null>(null);
  const refLayerRef = useRef<L.TileLayer | null>(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    tileLayerRef.current?.remove();
    refLayerRef.current?.remove();

    if (basemap === 'esri') {
      tileLayerRef.current = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
        { attribution: '&copy; Esri', maxZoom: 18 },
      ).addTo(map);
      refLayerRef.current = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 18, zIndex: 400 },
      ).addTo(map);
    } else {
      tileLayerRef.current = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19,
      }).addTo(map);
      refLayerRef.current = null;
    }
  }, [basemap]);

  // --- Fit to data on first load ---------------------------------------
  const fittedRef = useRef(false);
  // Memoised: an array literal recreated each render invalidated every
  // marker callback below, re-rendering the whole marker layer on any
  // parent state change (including the 5s aging tick).
  const junctionFeatures = useMemo(
    () => data?.layers.junctions?.features ?? [],
    [data],
  );

  const fitBounds = useCallback(() => {
    const map = mapRef.current;
    if (!map || junctionFeatures.length === 0) return;
    const bounds = L.latLngBounds(
      junctionFeatures.map(f => [f.latitude, f.longitude] as [number, number]),
    );
    map.fitBounds(bounds, { padding: [48, 48], maxZoom: 16 });
  }, [junctionFeatures]);

  useEffect(() => {
    if (fittedRef.current || junctionFeatures.length === 0) return;
    fittedRef.current = true;
    fitBounds();
  }, [junctionFeatures, fitBounds]);

  // --- Area selection ---------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (!areaMode) {
      map.dragging.enable();
      selectionRectRef.current?.remove();
      selectionRectRef.current = null;
      return;
    }

    // Dragging must be off or the map pans instead of drawing the box.
    map.dragging.disable();
    let origin: L.LatLng | null = null;

    const onDown = (e: L.LeafletMouseEvent) => {
      origin = e.latlng;
      selectionRectRef.current?.remove();
      selectionRectRef.current = L.rectangle(L.latLngBounds(origin, origin), {
        color: 'var(--its-text-accent)',
        weight: 1,
        dashArray: '4 3',
        fillOpacity: 0.08,
      }).addTo(map);
    };

    const onMove = (e: L.LeafletMouseEvent) => {
      if (!origin || !selectionRectRef.current) return;
      selectionRectRef.current.setBounds(L.latLngBounds(origin, e.latlng));
    };

    const onUp = (e: L.LeafletMouseEvent) => {
      if (!origin) return;
      const bounds = L.latLngBounds(origin, e.latlng);
      origin = null;

      const selected = junctionFeatures
        .filter(f => bounds.contains(L.latLng(f.latitude, f.longitude)))
        .map(f => f.id);

      onAreaSelect?.(selected);
      setAreaMode(false);
    };

    map.on('mousedown', onDown);
    map.on('mousemove', onMove);
    map.on('mouseup', onUp);

    return () => {
      map.off('mousedown', onDown);
      map.off('mousemove', onMove);
      map.off('mouseup', onUp);
      map.dragging.enable();
    };
  }, [areaMode, junctionFeatures, onAreaSelect]);

  // --- Marker rendering -------------------------------------------------
  const renderMarkers = useCallback(() => {
    const map = mapRef.current;
    const group = markerLayerRef.current;
    if (!map || !group || !data) return;

    group.clearLayers();

    // renderTick is a deliberate dependency: it is what re-evaluates every
    // marker's quality as time passes, so a junction that goes stale while
    // the operator is watching changes colour in place.
    void renderTick;
    const nowMs = Date.now();

    const projector = {
      project: (lat: number, lng: number) => {
        const point = map.latLngToContainerPoint([lat, lng]);
        return { x: point.x, y: point.y };
      },
    };

    const showHover = (event: L.LeafletMouseEvent, target: Omit<HoverTarget, 'x' | 'y'>) => {
      const originalEvent = event.originalEvent as MouseEvent;
      setHover({ ...target, x: originalEvent.clientX, y: originalEvent.clientY });
    };

    LAYER_ORDER.forEach(layerId => {
      if (!activeLayers.has(layerId)) return;
      const layer = data.layers[layerId];
      if (!layer || layer.features.length === 0) return;

      const meta = LAYER_META[layerId];

      const clusterable: ClusterableFeature[] = layer.features
        .filter(f => typeof f.latitude === 'number' && typeof f.longitude === 'number')
        .map(f => ({
          ...f,
          id: f.id,
          qualityState: featureQuality(f.quality, thresholds, nowMs),
        }));

      // Junctions cluster; overlay layers stay individually addressable so an
      // operator can always click the specific camera or incident they mean.
      const clusters =
        layerId === 'junctions'
          ? clusterFeatures(clusterable, projector, 58)
          : clusterable.map(f => ({
              id: f.id,
              latitude: f.latitude,
              longitude: f.longitude,
              members: [f],
              worstQuality: f.qualityState,
            }));

      clusters.forEach(cluster => {
        const appearance = qualityAppearance(cluster.worstQuality);

        // ---- Cluster bubble ----
        if (cluster.members.length > 1) {
          const size = Math.min(52, 30 + String(cluster.members.length).length * 7);
          const marker = L.marker([cluster.latitude, cluster.longitude], {
            icon: L.divIcon({
              className: '',
              html: `<div class="toc-cluster" style="width:${size}px;height:${size}px;background:${appearance.color};font-size:${size / 3}px;">${cluster.members.length}</div>`,
              iconSize: [size, size],
              iconAnchor: [size / 2, size / 2],
            }),
            keyboard: false,
          });

          marker.on('click', () => {
            map.fitBounds(
              L.latLngBounds(cluster.members.map(m => [m.latitude, m.longitude] as [number, number])),
              { padding: [56, 56] },
            );
          });

          marker.on('mouseover', (e: L.LeafletMouseEvent) => {
            const worst = worstQuality(cluster.members.map(m => m.qualityState));
            showHover(e, {
              title: `${cluster.members.length} ${meta.label.toLowerCase()}`,
              subtitle: 'Cluster — click to zoom in',
              rows: [
                ['Worst quality in cluster', qualityAppearance(worst).label],
                ['Members', cluster.members.map(m => m.name || m.code || m.id).slice(0, 6).join(', ')],
              ],
              provenance: null,
            });
          });
          marker.on('mouseout', () => setHover(null));
          marker.addTo(group);
          return;
        }

        // ---- Single feature ----
        const feature: any = cluster.members[0];
        const isSelected = selectedId === feature.id;
        const size = isSelected ? 30 : layerId === 'junctions' ? 20 : 16;

        const marker = L.marker([feature.latitude, feature.longitude], {
          icon: L.divIcon({
            className: '',
            html: `
              <div style="position:relative;width:${size}px;height:${size}px;display:flex;align-items:center;justify-content:center;">
                ${isSelected ? `<div style="position:absolute;inset:-6px;border-radius:50%;border:2px solid var(--its-border-focused);"></div>` : ''}
                <div style="
                  width:${size}px;height:${size}px;border-radius:${layerId === 'junctions' ? '50%' : '3px'};
                  background:${appearance.background};
                  border:2px solid ${appearance.color};
                  display:flex;align-items:center;justify-content:center;
                  box-shadow:var(--shadow-sm);
                ">
                  <div style="width:${Math.max(4, size / 3)}px;height:${Math.max(4, size / 3)}px;border-radius:50%;background:${appearance.color};"></div>
                </div>
              </div>`,
            iconSize: [size, size],
            iconAnchor: [size / 2, size / 2],
          }),
          title: feature.name || feature.title || feature.id,
          alt: `${meta.label}: ${feature.name || feature.title || feature.id}`,
          keyboard: true,
        });

        marker.on('click', () => {
          const junctionId =
            layerId === 'junctions' ? feature.id : feature.intersection_id;
          if (junctionId) onSelectJunction?.(junctionId);
        });

        marker.on('mouseover', (e: L.LeafletMouseEvent) => {
          const rows: Array<[string, string]> = [];

          if (layerId === 'junctions') {
            rows.push(['Code', feature.code ?? '—']);
            rows.push(['Controller', feature.controller?.connection_status ?? 'NOT CONFIGURED']);
            rows.push(['Active phase', feature.controller?.active_phase ?? 'NOT READ']);
            rows.push(['Traffic data', feature.traffic?.data_quality ?? 'NO DATA']);
            rows.push(['Open incidents', String(feature.open_incident_count ?? 0)]);
          } else if (layerId === 'cameras') {
            rows.push(['Stream', feature.stream_status ?? 'UNKNOWN']);
            rows.push(['Resolution', feature.resolution ?? 'NOT MEASURED']);
            rows.push(['FPS', feature.fps ?? 'NOT MEASURED']);
          } else if (layerId === 'sensors') {
            rows.push(['Type', feature.sensor_type ?? '—']);
            rows.push(['Health', feature.health_status ?? 'UNKNOWN']);
          } else if (layerId === 'incidents') {
            rows.push(['Severity', feature.severity ?? '—']);
            rows.push(['Status', feature.status ?? '—']);
            rows.push(['Type', feature.type ?? '—']);
          } else if (layerId === 'weather') {
            rows.push(['Road condition', feature.road_condition ?? 'UNKNOWN']);
            rows.push(['Precipitation', feature.precipitation_mm ?? 'NOT REPORTED']);
            rows.push(['Temperature', feature.temperature_c ?? 'NOT REPORTED']);
          } else if (layerId === 'transit') {
            rows.push(['Route', feature.route_id ?? '—']);
            rows.push(['Delay (s)', String(feature.delay_seconds ?? 0)]);
            rows.push(['Priority granted', String(feature.priority_granted)]);
          }

          showHover(e, {
            title: feature.name || feature.title || feature.route_id || meta.label,
            subtitle: feature.intersection_name
              ? `${meta.label} at ${feature.intersection_name}`
              : meta.label,
            rows,
            provenance: feature.quality ?? null,
            positionSource: feature.position_source,
          });
        });
        marker.on('mouseout', () => setHover(null));
        marker.addTo(group);
      });
    });
  }, [data, activeLayers, selectedId, onSelectJunction, thresholds, renderTick]);

  useEffect(() => {
    renderMarkers();
  }, [renderMarkers]);

  const toggleLayer = (id: LayerId) => {
    setActiveLayers(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const layerCounts = useMemo(() => {
    const counts: Partial<Record<LayerId, { count: number; empty: string | null }>> = {};
    LAYER_ORDER.forEach(id => {
      const layer = data?.layers[id];
      counts[id] = {
        count: layer?.features.length ?? 0,
        empty: layer?.empty_reason ?? null,
      };
    });
    return counts;
  }, [data]);

  return (
    <div style={{ position: 'relative', width: '100%', height, overflow: 'hidden' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%', zIndex: 1 }} />

      {/* Loading / error / empty overlays --------------------------------- */}
      {loading && (
        <div style={overlayStyle} role="status" aria-live="polite">
          <div className="skeleton" style={{ width: 180, height: 12, marginBottom: 10 }} />
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)' }}>
            Loading map layers…
          </div>
        </div>
      )}

      {!loading && error && (
        <div style={overlayStyle} role="alert">
          <AlertTriangle size={26} color="var(--its-signal-red)" />
          <div style={{ fontWeight: 700, marginTop: 8, color: 'var(--its-text-primary)' }}>
            MAP LAYERS UNAVAILABLE
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', maxWidth: 340, marginTop: 4 }}>
            {error}
          </div>
        </div>
      )}

      {!loading && !error && junctionFeatures.length === 0 && (
        <div style={overlayStyle}>
          <GitCommit size={26} color="var(--its-text-muted)" />
          <div style={{ fontWeight: 700, marginTop: 8, color: 'var(--its-text-primary)' }}>
            NO INFRASTRUCTURE CONFIGURED
          </div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-secondary)', maxWidth: 360, marginTop: 4, lineHeight: 1.5 }}>
            The map plots junctions you have configured. Nothing is placed on it
            until real infrastructure is connected.
          </div>
        </div>
      )}

      {/* Layer control ---------------------------------------------------- */}
      <div className="map-layer-panel" role="group" aria-label="Map layers">
        <div
          style={{
            fontSize: '10px', fontWeight: 700, letterSpacing: '0.08em',
            color: 'var(--its-text-muted)', padding: '2px 6px 6px',
          }}
        >
          LAYERS
        </div>

        {LAYER_ORDER.map(id => {
          const meta = LAYER_META[id];
          const info = layerCounts[id]!;
          const active = activeLayers.has(id);

          return (
            <label key={id} className="map-layer-row" title={info.empty ?? `${info.count} features`}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                <input
                  type="checkbox"
                  checked={active}
                  onChange={() => toggleLayer(id)}
                  aria-label={`${meta.label} layer`}
                  style={{ accentColor: 'var(--its-text-accent)' }}
                />
                <span style={{ color: meta.color, display: 'flex' }}>{meta.icon}</span>
                <span style={{ color: active ? 'var(--its-text-primary)' : 'var(--its-text-muted)' }}>
                  {meta.label}
                </span>
              </span>

              <span
                className="mono"
                style={{
                  fontSize: '10px',
                  color: info.count > 0 ? 'var(--its-text-secondary)' : 'var(--its-text-disabled)',
                }}
              >
                {info.count > 0 ? info.count : '—'}
              </span>
            </label>
          );
        })}

        {/* Layers with nothing in them say why, rather than looking broken. */}
        {LAYER_ORDER.filter(id => activeLayers.has(id) && layerCounts[id]!.empty).map(id => (
          <div
            key={`empty-${id}`}
            style={{
              fontSize: '9px', color: 'var(--its-text-muted)', padding: '3px 6px',
              fontFamily: 'var(--font-mono)', borderTop: '1px solid var(--its-border-subtle)',
              marginTop: '4px',
            }}
          >
            {LAYER_META[id].label.toUpperCase()}: {layerCounts[id]!.empty}
          </div>
        ))}
      </div>

      {/* Toolbar ---------------------------------------------------------- */}
      <div
        style={{
          position: 'absolute', top: '12px', right: '12px', zIndex: 500,
          display: 'flex', gap: '6px', background: 'var(--its-bg-glass)',
          backdropFilter: 'blur(8px)', border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-md)', padding: '4px', boxShadow: 'var(--shadow-sm)',
        }}
      >
        <button onClick={fitBounds} className="its-btn" style={toolbarBtn} title="Fit all junctions in view">
          <Maximize2 size={13} />
          <span>Fit</span>
        </button>

        <button
          onClick={() => {
            const map = mapRef.current;
            const selected = junctionFeatures.find(f => f.id === selectedId);
            if (map && selected) map.flyTo([selected.latitude, selected.longitude], 16, { duration: 0.7 });
            else fitBounds();
          }}
          className="its-btn"
          style={toolbarBtn}
          title="Centre on the selected junction"
        >
          <Crosshair size={13} />
          <span>Centre</span>
        </button>

        <button
          onClick={() => setAreaMode(v => !v)}
          className="its-btn"
          aria-pressed={areaMode}
          style={{
            ...toolbarBtn,
            borderColor: areaMode ? 'var(--its-border-focused)' : undefined,
            color: areaMode ? 'var(--its-text-accent)' : undefined,
          }}
          title="Drag a box to select junctions for a bulk report"
        >
          <SquareDashedMousePointer size={13} />
          <span>{areaMode ? 'Drawing…' : 'Area'}</span>
        </button>

        <button
          onClick={() => setBasemap(b => (b === 'esri' ? 'osm' : 'esri'))}
          className="its-btn"
          style={toolbarBtn}
          title="Switch basemap"
        >
          <Layers size={13} />
          <span>{basemap === 'esri' ? 'ESRI' : 'OSM'}</span>
        </button>
      </div>

      {areaMode && (
        <div
          role="status"
          style={{
            position: 'absolute', top: '58px', right: '12px', zIndex: 500,
            background: 'var(--its-bg-glass)', border: '1px solid var(--its-border-focused)',
            borderRadius: 'var(--radius-sm)', padding: '5px 9px',
            fontSize: 'var(--text-2xs)', color: 'var(--its-text-accent)',
            fontFamily: 'var(--font-mono)', backdropFilter: 'blur(8px)',
          }}
        >
          DRAG A BOX TO SELECT JUNCTIONS
        </div>
      )}

      {/* Status footer ---------------------------------------------------- */}
      <div
        style={{
          position: 'absolute', bottom: '8px', left: '8px', zIndex: 500,
          background: 'var(--its-bg-glass)', backdropFilter: 'blur(6px)',
          border: '1px solid var(--its-border-subtle)', borderRadius: 'var(--radius-xs)',
          padding: '3px 8px', display: 'flex', alignItems: 'center', gap: '8px',
          fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--its-text-secondary)',
        }}
      >
        <span>ZOOM {zoom}</span>
        <span style={{ color: 'var(--its-border-default)' }}>|</span>
        <span>EPSG:3857</span>
        {data && (
          <>
            <span style={{ color: 'var(--its-border-default)' }}>|</span>
            <span title={formatTimestamp(data.generated_at)}>
              LAYERS AS OF {formatAge((nowMs - new Date(data.generated_at).getTime()) / 1000)} AGO
            </span>
          </>
        )}
      </div>

      {/* Hover provenance card -------------------------------------------- */}
      {hover && (
        <div
          className="map-hover-card"
          style={{
            left: Math.min(hover.x + 14, window.innerWidth - 300),
            top: Math.min(hover.y + 14, window.innerHeight - 260),
            background: 'var(--its-bg-surface)',
            border: '1px solid var(--its-border-default)',
            padding: '10px 12px',
            minWidth: '250px',
            maxWidth: '290px',
          }}
        >
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-primary)' }}>
            {hover.title}
          </div>
          <div style={{ fontSize: '10px', color: 'var(--its-text-muted)', marginBottom: '8px' }}>
            {hover.subtitle}
          </div>

          {hover.rows.map(([label, value]) => (
            <div
              key={label}
              style={{
                display: 'flex', justifyContent: 'space-between', gap: '12px',
                fontSize: 'var(--text-2xs)', marginBottom: '3px',
              }}
            >
              <span style={{ color: 'var(--its-text-muted)' }}>{label}</span>
              <span className="mono" style={{ color: 'var(--its-text-primary)', textAlign: 'right' }}>
                {String(value)}
              </span>
            </div>
          ))}

          {/* Provenance, always, including when it is absent. */}
          <div
            style={{
              marginTop: '8px', paddingTop: '8px',
              borderTop: '1px solid var(--its-border-subtle)',
              fontSize: '10px', color: 'var(--its-text-secondary)', lineHeight: 1.6,
            }}
          >
            <div>
              SOURCE: <span className="mono">{formatSource(hover.provenance?.source)}</span>
            </div>
            <div>
              OBSERVED: <span className="mono">{formatTimestamp(hover.provenance?.observed_at)}</span>
            </div>
            <div>
              QUALITY:{' '}
              <span
                className="mono"
                style={{
                  color: qualityAppearance(
                    featureQuality(hover.provenance, thresholds, nowMs),
                  ).color,
                  fontWeight: 700,
                }}
              >
                {qualityAppearance(featureQuality(hover.provenance, thresholds, nowMs)).label}
              </span>
            </div>
            {hover.positionSource && hover.positionSource !== 'CONFIGURED_INTERSECTION_COORDINATES' && (
              <div style={{ marginTop: '4px', color: 'var(--its-text-muted)' }}>
                POSITION: {hover.positionSource}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const overlayStyle: React.CSSProperties = {
  position: 'absolute',
  inset: 0,
  zIndex: 600,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  padding: '24px',
  background: 'var(--its-bg-glass)',
  backdropFilter: 'blur(2px)',
};

const toolbarBtn: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: '11px',
  height: '28px',
  gap: '4px',
};
