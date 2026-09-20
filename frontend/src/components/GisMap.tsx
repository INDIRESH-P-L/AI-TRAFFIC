import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Maximize2, Crosshair, Layers, Navigation } from 'lucide-react';

interface IntersectionMarker {
  id: string;
  name: string;
  code?: string;
  latitude: number;
  longitude: number;
  operational_status?: string;
  controller_status?: string;
  signal_state?: 'RED' | 'YELLOW' | 'GREEN' | string;
  congestion_level?: string;
}

interface GisMapProps {
  intersections: IntersectionMarker[];
  selectedId?: string | null;
  onSelectIntersection?: (id: string) => void;
  height?: string;
  showControls?: boolean;
}

export const GisMap: React.FC<GisMapProps> = ({
  intersections = [],
  selectedId,
  onSelectIntersection,
  height = '100%',
  showControls = true,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const markersRef = useRef<Map<string, L.Marker>>(new Map());
  const layersRef = useRef<{ base: L.TileLayer; ref: L.TileLayer; osm: L.TileLayer } | null>(null);

  const [activeLayer, setActiveLayer] = useState<'esri' | 'osm'>('esri');
  const [cursorCoords, setCursorCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [zoomLevel, setZoomLevel] = useState<number>(14);

  // Initialize map once
  useEffect(() => {
    if (!mapContainerRef.current) return;

    if (!mapInstanceRef.current) {
      const defaultLat = intersections.length > 0 ? intersections[0].latitude : 37.7749;
      const defaultLng = intersections.length > 0 ? intersections[0].longitude : -122.4194;

      const map = L.map(mapContainerRef.current, {
        center: [defaultLat, defaultLng],
        zoom: intersections.length > 0 ? 14 : 13,
        zoomControl: showControls,
        attributionControl: false,
      });

      // 1. Esri World Light Gray Base & Reference (Standard DOT ITS Basemap, 100% Watermark-Free)
      const esriBase = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
        {
          attribution: '&copy; Esri, DeLorme, NAVTEQ',
          maxZoom: 18,
        }
      ).addTo(map);

      const esriRef = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
        {
          maxZoom: 18,
          zIndex: 400,
        }
      ).addTo(map);

      // 2. OpenStreetMap Alternative Layer
      const osmLayer = L.tileLayer(
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        {
          attribution: '&copy; OpenStreetMap contributors',
          maxZoom: 19,
        }
      );

      layersRef.current = { base: esriBase, ref: esriRef, osm: osmLayer };

      L.control.attribution({
        position: 'bottomright',
        prefix: 'TRAFFICINTEL GIS • ESRI DOT CANVAS & REFERENCE',
      }).addTo(map);

      // Cursor movement telemetry
      map.on('mousemove', (e) => {
        setCursorCoords({ lat: e.latlng.lat, lng: e.latlng.lng });
      });

      map.on('zoomend', () => {
        setZoomLevel(map.getZoom());
      });

      mapInstanceRef.current = map;
    }

    return () => {
      // Map cleanup on unmount
    };
  }, []);

  // Toggle basemap layers
  const toggleLayer = () => {
    const map = mapInstanceRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;

    if (activeLayer === 'esri') {
      map.removeLayer(layers.base);
      map.removeLayer(layers.ref);
      layers.osm.addTo(map);
      setActiveLayer('osm');
    } else {
      map.removeLayer(layers.osm);
      layers.base.addTo(map);
      layers.ref.addTo(map);
      setActiveLayer('esri');
    }
  };

  // Fit all intersection markers in view
  const handleFitBounds = () => {
    const map = mapInstanceRef.current;
    if (!map || intersections.length === 0) return;

    const bounds = L.latLngBounds(intersections.map(i => [i.latitude, i.longitude]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
  };

  // Recenter on selected intersection
  const handleCenterSelected = () => {
    const map = mapInstanceRef.current;
    if (!map) return;

    if (selectedId) {
      const selected = intersections.find(i => i.id === selectedId);
      if (selected) {
        map.flyTo([selected.latitude, selected.longitude], 15, { duration: 0.8 });
        return;
      }
    }
    handleFitBounds();
  };

  // Update markers when intersections list or selection changes
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Clear removed markers
    const currentIds = new Set(intersections.map(i => i.id));
    markersRef.current.forEach((marker, id) => {
      if (!currentIds.has(id)) {
        marker.remove();
        markersRef.current.delete(id);
      }
    });

    if (intersections.length > 0) {
      intersections.forEach((inter) => {
        const isSelected = selectedId === inter.id;

        // Core status color
        let statusColor = '#10b981'; // Green
        let glowColor = 'rgba(16, 185, 129, 0.25)';
        if (inter.operational_status === 'DEGRADED' || inter.signal_state === 'YELLOW') {
          statusColor = '#f59e0b';
          glowColor = 'rgba(245, 158, 11, 0.25)';
        } else if (inter.operational_status === 'CRITICAL' || inter.operational_status === 'OFFLINE' || inter.signal_state === 'RED') {
          statusColor = '#ef4444';
          glowColor = 'rgba(239, 68, 68, 0.25)';
        }

        if (isSelected) {
          statusColor = '#2563eb';
          glowColor = 'rgba(37, 99, 235, 0.35)';
        }

        const markerHtml = `
          <div style="
            position: relative;
            width: ${isSelected ? '36px' : '24px'};
            height: ${isSelected ? '36px' : '24px'};
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
          ">
            ${isSelected ? `
              <!-- Radar Sweep Ring 1 -->
              <div style="
                position: absolute;
                inset: -6px;
                border-radius: 50%;
                border: 1.5px solid #2563eb;
                animation: radarPulse 2s infinite cubic-bezier(0.2, 0.8, 0.2, 1);
                pointer-events: none;
              "></div>
              <!-- Radar Sweep Ring 2 -->
              <div style="
                position: absolute;
                inset: -12px;
                border-radius: 50%;
                border: 1px solid rgba(37, 99, 235, 0.4);
                animation: radarPulse 2s infinite cubic-bezier(0.2, 0.8, 0.2, 1) 0.6s;
                pointer-events: none;
              "></div>
            ` : ''}

            <!-- Status Base Halo -->
            <div style="
              position: absolute;
              inset: 0;
              border-radius: 50%;
              background: ${glowColor};
              box-shadow: 0 1px 6px ${glowColor};
            "></div>

            <!-- Inner White Core Node -->
            <div style="
              position: relative;
              width: ${isSelected ? '18px' : '14px'};
              height: ${isSelected ? '18px' : '14px'};
              border-radius: 50%;
              background: #ffffff;
              border: 2px solid ${statusColor};
              display: flex;
              align-items: center;
              justify-content: center;
              box-shadow: 0 2px 5px rgba(15, 23, 42, 0.15);
            ">
              <div style="
                width: ${isSelected ? '7px' : '5px'};
                height: ${isSelected ? '7px' : '5px'};
                border-radius: 50%;
                background: ${statusColor};
              "></div>
            </div>
          </div>
        `;

        const customIcon = L.divIcon({
          className: 'toc-gis-marker',
          html: markerHtml,
          iconSize: [isSelected ? 36 : 24, isSelected ? 36 : 24],
          iconAnchor: [isSelected ? 18 : 12, isSelected ? 18 : 12],
        });

        let marker = markersRef.current.get(inter.id);
        if (marker) {
          marker.setLatLng([inter.latitude, inter.longitude]);
          marker.setIcon(customIcon);
        } else {
          marker = L.marker([inter.latitude, inter.longitude], { icon: customIcon }).addTo(map);
          marker.on('click', () => {
            if (onSelectIntersection) {
              onSelectIntersection(inter.id);
            }
          });
          markersRef.current.set(inter.id, marker);
        }

        // Clean Light Industrial Popup
        marker.bindPopup(`
          <div style="font-family: 'Inter', sans-serif; font-size: 12px; color: #0f172a; padding: 2px;">
            <div style="font-weight: 700; font-size: 13px; color: #1e3a8a; margin-bottom: 2px;">
              ${inter.name}
            </div>
            <div style="font-size: 10px; color: #64748b; font-family: monospace; margin-bottom: 6px;">
              GIS: ${inter.latitude.toFixed(5)}, ${inter.longitude.toFixed(5)}
            </div>
            <div style="display: flex; justify-content: space-between; gap: 12px; margin-bottom: 4px; font-size: 11px;">
              <span style="color: #64748b;">STATUS:</span>
              <span style="font-weight: 700; color: ${statusColor};">${inter.operational_status || 'HEALTHY'}</span>
            </div>
            <div style="display: flex; justify-content: space-between; gap: 12px; font-size: 11px;">
              <span style="color: #64748b;">CONTROLLER:</span>
              <span style="font-weight: 600; color: #334155;">${inter.controller_status || 'CONNECTED'}</span>
            </div>
          </div>
        `);
      });

      if (selectedId) {
        const selected = intersections.find(i => i.id === selectedId);
        if (selected) {
          map.panTo([selected.latitude, selected.longitude], { animate: true });
        }
      }
    }
  }, [intersections, selectedId, onSelectIntersection]);

  return (
    <div style={{ width: '100%', height, position: 'relative', overflow: 'hidden' }}>
      {/* Primary Leaflet Container */}
      <div
        ref={mapContainerRef}
        style={{
          width: '100%',
          height: '100%',
          position: 'relative',
          zIndex: 1,
        }}
      />

      {/* Floating Tactical HUD Bar (Top-Right) */}
      <div
        style={{
          position: 'absolute',
          top: '12px',
          right: '12px',
          zIndex: 500,
          display: 'flex',
          gap: '6px',
          background: 'rgba(255, 255, 255, 0.95)',
          backdropFilter: 'blur(8px)',
          border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-md)',
          padding: '4px',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <button
          onClick={handleCenterSelected}
          className="its-btn"
          style={{ padding: '4px 8px', fontSize: '11px', height: '28px', gap: '4px' }}
          title="Center on selected intersection"
        >
          <Crosshair size={13} color="var(--its-text-accent)" />
          <span>Center</span>
        </button>

        <button
          onClick={handleFitBounds}
          className="its-btn"
          style={{ padding: '4px 8px', fontSize: '11px', height: '28px', gap: '4px' }}
          title="Fit all arterial nodes into view"
        >
          <Maximize2 size={13} />
          <span>Fit Extent</span>
        </button>

        <button
          onClick={toggleLayer}
          className="its-btn"
          style={{ padding: '4px 8px', fontSize: '11px', height: '28px', gap: '4px' }}
          title="Switch basemap between Esri DOT Canvas and OpenStreetMap"
        >
          <Layers size={13} color="var(--its-text-teal)" />
          <span>{activeLayer === 'esri' ? 'ESRI DOT' : 'OSM'}</span>
        </button>
      </div>

      {/* GIS Coordinate Telemetry HUD (Bottom-Left) */}
      <div
        style={{
          position: 'absolute',
          bottom: '8px',
          left: '8px',
          zIndex: 500,
          background: 'rgba(255, 255, 255, 0.92)',
          backdropFilter: 'blur(6px)',
          border: '1px solid var(--its-border-subtle)',
          borderRadius: 'var(--radius-xs)',
          padding: '3px 8px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '10px',
          fontFamily: 'var(--font-mono)',
          color: 'var(--its-text-secondary)',
          boxShadow: 'var(--shadow-xs)',
          pointerEvents: 'none',
        }}
      >
        <Navigation size={10} color="var(--its-text-accent)" />
        <span>
          {cursorCoords
            ? `${cursorCoords.lat.toFixed(5)}° N, ${cursorCoords.lng.toFixed(5)}° W`
            : `${(intersections[0]?.latitude || 37.7749).toFixed(5)}° N, ${(intersections[0]?.longitude || -122.4194).toFixed(5)}° W`}
        </span>
        <span style={{ color: 'var(--its-border-default)' }}>|</span>
        <span>ZOOM: {zoomLevel}x</span>
        <span style={{ color: 'var(--its-border-default)' }}>|</span>
        <span style={{ color: 'var(--its-text-teal)' }}>EPSG:3857</span>
      </div>
    </div>
  );
};
