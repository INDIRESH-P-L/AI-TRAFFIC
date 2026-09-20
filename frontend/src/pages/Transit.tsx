import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { TruthfulEmptyState } from '../components/TruthfulEmptyState';
import { Bus } from 'lucide-react';

export const Transit: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.getTransitEvents();
        setData(res);
      } catch (err) {
        console.error('Failed to load transit data', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>Public Transit Priority (TSP)</h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--its-text-secondary)', marginTop: '2px' }}>
            GTFS-Realtime vehicle position and schedule delay priority telemetry.
          </p>
        </div>

        <StatusBadge status={data?.status || 'TRANSIT_FEED_NOT_CONFIGURED'} />
      </div>

      {(!data?.events || data.events.length === 0) && !loading ? (
        <TruthfulEmptyState
          title="TRANSIT TELEMETRY NOT CONFIGURED"
          description="No municipal GTFS or GTFS-Realtime vehicle location feed is configured. Fictional transit vehicles are strictly prohibited."
          icon={<Bus size={36} />}
        />
      ) : (
        <div className="its-card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="its-table">
            <thead>
              <tr>
                <th>Route</th>
                <th>Vehicle ID</th>
                <th>Schedule Delay</th>
                <th>Priority Requested</th>
                <th>Priority Granted</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {data.events.map((ev: any) => (
                <tr key={ev.id}>
                  <td style={{ fontWeight: 600 }}>{ev.route_id}</td>
                  <td className="mono">{ev.vehicle_id}</td>
                  <td>{ev.delay_seconds} sec</td>
                  <td>{ev.priority_requested ? 'YES' : 'NO'}</td>
                  <td>{ev.priority_granted ? 'GRANTED' : 'HELD'}</td>
                  <td style={{ fontSize: 'var(--text-xs)' }}>{ev.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
