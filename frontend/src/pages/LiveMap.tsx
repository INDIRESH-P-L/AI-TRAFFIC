import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FileText, RefreshCw, X } from 'lucide-react';
import { api } from '../api/client';
import { OperationsMap } from '../components/map/OperationsMap';
import type { MapData } from '../components/map/OperationsMap';
import { JunctionDrawer } from '../components/JunctionDrawer';
import { TimeScrubber } from '../components/TimeScrubber';
import { SignalCommandWorkflow } from '../components/SignalCommandWorkflow';
import { ProvenanceChip } from '../components/provenance/Provenance';
import { SkeletonRows } from '../components/Skeleton';
import { useConsole } from '../context/ConsoleContext';
import { formatAge, normalizeQuality, qualityAppearance, qualityForAge } from '../lib/quality';
import { useTickingAge } from '../hooks/useTickingAge';

/**
 * TRAFFICINTEL AI - Live GIS Operations
 *
 * The map is the primary surface; everything else on this page is a
 * click-through from it. Layer data refreshes on a slow backstop poll and
 * immediately on any relevant live event, so the operator does not have to
 * decide when to press refresh.
 */

export const LiveMap: React.FC = () => {
  const [data, setData] = useState<MapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [areaSelection, setAreaSelection] = useState<string[] | null>(null);
  const [commandControllerId, setCommandControllerId] = useState<string | null | undefined>(undefined);
  const [controllers, setControllers] = useState<any[]>([]);

  const { subscribe } = useConsole();
  const generatedAge = useTickingAge(data?.generated_at);

  const load = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    setError(null);
    try {
      const [layers, controllerList] = await Promise.all([
        api.getMapLayers(),
        api.getControllers().catch(() => []),
      ]);
      setData(layers);
      setControllers(controllerList);
    } catch (err: any) {
      setError(err.message || 'Could not load map layers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(true);
  }, [load]);

  // Live: any signal or incident event re-reads the layers.
  useEffect(() => {
    const unsubSignal = subscribe('signal.*', () => load());
    const unsubIncident = subscribe('incident.*', () => load());
    return () => {
      unsubSignal();
      unsubIncident();
    };
  }, [subscribe, load]);

  // Backstop poll: quality states age even when nothing is emitted.
  useEffect(() => {
    const timer = setInterval(() => load(), 30000);
    return () => clearInterval(timer);
  }, [load]);

  const junctions = data?.layers.junctions?.features ?? [];
  const selectedFeature = junctions.find(f => f.id === (drawerId ?? selectedId));
  const thresholds = data?.quality_thresholds_sec;

  // Quality roll-up across the network, computed from real ages.
  const qualitySummary = useMemo(() => {
    const counts: Record<string, number> = {};
    const now = Date.now();
    junctions.forEach(feature => {
      const provenance = feature.traffic?.quality;
      const state = provenance?.observed_at
        ? qualityForAge((now - new Date(provenance.observed_at).getTime()) / 1000, thresholds)
        : normalizeQuality(feature.traffic?.data_quality);
      counts[state] = (counts[state] ?? 0) + 1;
    });
    return counts;
  }, [junctions, thresholds]);

  const areaSelectedJunctions = useMemo(
    () => (areaSelection ? junctions.filter(f => areaSelection.includes(f.id)) : []),
    [areaSelection, junctions],
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* Network quality roll-up ---------------------------------------- */}
      <div className="its-card">
        <div className="its-card-header">
          <span className="its-card-title">Network Data Quality</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {data && (
              <span className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                LAYERS {formatAge(generatedAge)} OLD
              </span>
            )}
            <button onClick={() => load(true)} className="its-btn" style={{ padding: '3px 8px' }}>
              <RefreshCw size={12} className={loading ? 'pulse-indicator' : ''} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {loading && !data ? (
          <SkeletonRows rows={1} label="Network quality" />
        ) : junctions.length === 0 ? (
          <div
            className="mono"
            style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--its-text-muted)' }}
          >
            SYSTEM READY - NO TRAFFIC INFRASTRUCTURE IS CURRENTLY CONNECTED
          </div>
        ) : (
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
            {Object.entries(qualitySummary).map(([state, count]) => {
              const appearance = qualityAppearance(state as any);
              return (
                <div key={state} style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                  <span
                    style={{
                      width: 10, height: 10, borderRadius: '50%',
                      background: appearance.color, border: `1px solid ${appearance.border}`,
                    }}
                  />
                  <span className="mono" style={{ fontSize: 'var(--text-xs)', fontWeight: 700 }}>
                    {count}
                  </span>
                  <span style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-muted)' }}>
                    {appearance.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Map -------------------------------------------------------------- */}
      <div
        className="its-card"
        style={{ padding: 0, overflow: 'hidden', height: 'min(62vh, 620px)', minHeight: '360px' }}
      >
        <OperationsMap
          data={data}
          loading={loading && !data}
          error={error}
          selectedId={selectedId}
          onSelectJunction={id => {
            setSelectedId(id);
            setDrawerId(id);
          }}
          onAreaSelect={ids => setAreaSelection(ids)}
        />
      </div>

      {/* Area selection bulk report --------------------------------------- */}
      {areaSelection && (
        <div className="its-card">
          <div className="its-card-header">
            <span className="its-card-title">
              <FileText size={14} color="var(--its-text-accent)" />
              <span>Area Selection Report</span>
            </span>
            <button
              onClick={() => setAreaSelection(null)}
              className="its-btn"
              style={{ padding: '3px 8px' }}
              aria-label="Clear area selection"
            >
              <X size={12} />
              <span>Clear</span>
            </button>
          </div>

          {areaSelectedJunctions.length === 0 ? (
            <div
              className="mono"
              style={{ fontSize: 'var(--text-xs)', color: 'var(--its-text-muted)', fontWeight: 700 }}
            >
              NO JUNCTIONS INSIDE THE SELECTED AREA
            </div>
          ) : (
            <>
              <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--its-text-secondary)', marginBottom: '10px' }}>
                {areaSelectedJunctions.length} junction
                {areaSelectedJunctions.length === 1 ? '' : 's'} selected. Every row reports the
                state that was actually read; nothing is summarised across junctions that
                have not reported.
              </div>

              <div className="its-table-container">
                <table className="its-table">
                  <thead>
                    <tr>
                      <th>Junction</th>
                      <th>Controller</th>
                      <th>Green now</th>
                      <th>Traffic data</th>
                      <th>Open incidents</th>
                    </tr>
                  </thead>
                  <tbody>
                    {areaSelectedJunctions.map(feature => (
                      <tr key={feature.id}>
                        <td>
                          <button
                            onClick={() => {
                              setSelectedId(feature.id);
                              setDrawerId(feature.id);
                            }}
                            style={{
                              background: 'transparent', border: 'none', padding: 0,
                              color: 'var(--its-text-accent)', cursor: 'pointer',
                              fontWeight: 600, fontSize: 'inherit',
                            }}
                          >
                            {feature.name}
                          </button>
                          <div className="mono" style={{ fontSize: '10px', color: 'var(--its-text-muted)' }}>
                            {feature.code}
                          </div>
                        </td>
                        <td className="mono">{feature.controller?.connection_status ?? 'NOT CONFIGURED'}</td>
                        <td className="mono">
                          {feature.controller?.active_phase ?? 'NOT READ'}
                        </td>
                        <td>
                          <ProvenanceChip
                            provenance={feature.traffic?.quality}
                            thresholds={thresholds}
                            compact
                          />
                        </td>
                        <td className="mono">{feature.open_incident_count ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {/* Historical replay for the selected junction ---------------------- */}
      <TimeScrubber
        junctionId={drawerId ?? selectedId}
        junctionName={selectedFeature?.name}
      />

      {/* Drawers ---------------------------------------------------------- */}
      {drawerId && (
        <JunctionDrawer
          junctionId={drawerId}
          mapFeature={selectedFeature}
          thresholds={thresholds}
          onClose={() => setDrawerId(null)}
          onIssueCommand={controllerId => setCommandControllerId(controllerId)}
        />
      )}

      {commandControllerId !== undefined && (
        <SignalCommandWorkflow
          controllers={controllers}
          preselectedControllerId={commandControllerId}
          onClose={() => setCommandControllerId(undefined)}
          onExecuted={() => load()}
        />
      )}
    </div>
  );
};
